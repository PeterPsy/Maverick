"""Hostile integration tests for the production confined-sidecar launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from core.api.sidecar_proxy import HttpSidecarManager, RunningSidecar, UnixRelayHTTPConnection, _proxy_to_running_sidecar
from core.apps.contracts import (
    build_http_sidecar_data_mount,
    build_http_sidecar_model_access,
    build_http_sidecar_process_policy,
    build_http_sidecar_spec,
)
from core.apps.errors import AppHostingError
from core.apps.models import HttpSidecarBindSpec, HttpSidecarHealthSpec
from core.apps.sidecar_execution import MINIMAL_SIDECAR_ENV, prepare_confined_sidecar_launch, relay_preamble
from core.shared.entrypoints import EntrypointShutdownController


class ConfinedSidecarExecutionIntegrationTests(unittest.TestCase):
    def test_production_launcher_confines_environment_filesystem_network_relay_and_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            source_root = repo_root / "apps" / "probe"
            source_root.mkdir(parents=True)
            workspace_root = repo_root / "workspaces" / "default"
            workspace_root.mkdir(parents=True)
            data_root = workspace_root / "data" / "probe"
            native_data_root = data_root / "opendesign-native"
            operator_home = repo_root / "operator-home"
            other_workspace = repo_root / "workspaces" / "other" / "data" / "probe"
            operator_home.mkdir()
            other_workspace.mkdir(parents=True)
            native_data_root.mkdir(parents=True)
            (data_root / "official-update.json").write_text("host-control", encoding="utf-8")
            (operator_home / "secret").write_text("operator-secret", encoding="utf-8")
            (other_workspace / "secret").write_text("other-workspace-secret", encoding="utf-8")

            host_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            host_listener.bind(("127.0.0.1", 0))
            host_listener.listen(1)
            self.addCleanup(host_listener.close)
            source_root.joinpath("server.py").write_text(
                _probe_server_source(
                    operator_secret=operator_home / "secret",
                    other_workspace_secret=other_workspace / "secret",
                    host_port=int(host_listener.getsockname()[1]),
                ),
                encoding="utf-8",
            )

            sidecar = build_http_sidecar_spec(
                service_id="probe",
                runtime="python",
                command=["python3", "server.py"],
                env={
                    "PROBE_PORT": "${service.port}",
                    "PROBE_TOKEN": "${service.token}",
                },
                process_policy=build_http_sidecar_process_policy(
                    memory_bytes=512 * 1024 * 1024,
                    open_files=256,
                    request_concurrency=1,
                ),
                data_mount=build_http_sidecar_data_mount(subpath="opendesign-native"),
                model_access=build_http_sidecar_model_access(
                    api=True,
                    cli=["codex"],
                    required=False,
                ),
                bind=HttpSidecarBindSpec(host="127.0.0.1", port="auto"),
                health=HttpSidecarHealthSpec(path="/health", timeout_ms=8000),
            )
            manager = HttpSidecarManager()
            shutdown = EntrypointShutdownController()
            self.addCleanup(shutdown.begin_shutdown)

            with (
                patch.dict(
                    os.environ,
                    {
                        "MAVERICK_WP1_HOST_SENTINEL": "must-not-cross",
                        "HOME": str(operator_home),
                        "OPENAI_API_KEY": "provider-secret",
                        "CODEX_HOME": "/operator-runtime-home",
                        "MAVERICK_BOOTSTRAP_SECRET": "bootstrap-secret",
                        "MAVERICK_RUNTIME_API_TOKEN": "runtime-secret",
                        "MAVERICK_SESSION_COOKIE": "platform-cookie",
                    },
                ),
                patch(
                    "core.api.sidecar_proxy.issue_model_access_lease",
                    return_value=None,
                ) as issue_model_access,
            ):
                running = manager.ensure_running(
                    workspace_id="default",
                    app_id="probe",
                    source_root=source_root,
                    data_root=str(data_root),
                    sidecar=sidecar,
                    start_path=repo_root,
                    shutdown_controller=shutdown,
                )
            self.assertEqual(
                issue_model_access.call_args.kwargs["data_root"],
                native_data_root.resolve(),
            )

            relay_path = running.confined_launch.relay_socket
            self.assertEqual(stat.S_IMODE(relay_path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(relay_path.stat().st_mode), 0o600)
            with self.assertRaises(OSError):
                socket.create_connection((running.host, running.port), timeout=0.25)
            self._assert_relay_rejects_unauthenticated_request(relay_path)
            self._assert_relay_enforces_concurrency(running)

            connection = UnixRelayHTTPConnection(running, timeout=3)
            connection.request(
                "GET",
                "/probe",
                headers={
                    "Authorization": f"Bearer {running.token}",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 200)
            for key in (
                "sentinel_absent",
                "home_absent",
                "provider_secret_absent",
                "runtime_secret_absent",
                "bootstrap_secret_absent",
                "cookie_absent",
                "provider_home_absent",
                "relay_capability_absent_from_env",
                "sandbox_home_is_ephemeral",
                "host_clis_absent",
                "operator_home_absent",
                "other_workspace_absent",
                "control_metadata_absent",
                "bundle_read_only",
                "outside_write_denied",
                "data_write_allowed",
                "no_default_route",
                "host_loopback_denied",
                "metadata_denied",
                "internet_denied",
                "technical_token_present",
                "descendant_started",
            ):
                self.assertTrue(payload[key], key)
            self.assertEqual(payload["memory_limit"], 512 * 1024 * 1024)
            self.assertEqual(payload["open_files_limit"], 256)
            self.assertEqual((native_data_root / "allowed.txt").read_text(encoding="utf-8"), "allowed")
            self.assertEqual(
                (data_root / "official-update.json").read_text(encoding="utf-8"),
                "host-control",
            )

            self.assertTrue(running.request_slots.acquire(blocking=False))
            try:
                with self.assertRaisesRegex(AppHostingError, "concurrency limit"):
                    _proxy_to_running_sidecar(
                        running,
                        method="GET",
                        path="/health",
                        query_string="",
                        environ={},
                        body=b"",
                        start_response=lambda _status, _headers: None,
                    )
            finally:
                running.request_slots.release()

            descendants = _descendant_pids(running.process.pid)
            self.assertGreaterEqual(len(descendants), 2)
            relay_directory = running.confined_launch.relay_directory
            manager.stop_app(workspace_id="default", app_id="probe")
            self.assertEqual(shutdown.active_process_count(), 0)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and any(Path(f"/proc/{pid}").exists() for pid in descendants):
                time.sleep(0.05)
            self.assertFalse(any(Path(f"/proc/{pid}").exists() for pid in descendants))
            self.assertFalse(relay_path.exists())
            self.assertFalse(relay_directory.exists())

    def test_missing_bubblewrap_and_absolute_command_fail_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            source_root = repo_root / "apps" / "probe"
            source_root.mkdir(parents=True)
            workspace_root = repo_root / "workspaces" / "default"
            workspace_root.mkdir(parents=True)
            data_root = workspace_root / "data" / "probe"
            sidecar = build_http_sidecar_spec(service_id="probe", command=["python3", "server.py"])

            with patch("core.apps.sidecar_execution.shutil.which", return_value=None):
                with self.assertRaisesRegex(AppHostingError, "bubblewrap is required.*no fallback"):
                    prepare_confined_sidecar_launch(
                        workspace_id="default",
                        app_id="probe",
                        source_root=source_root,
                        data_root=data_root,
                        workspace_root=workspace_root,
                        sidecar=sidecar,
                        port=12345,
                        env=dict(MINIMAL_SIDECAR_ENV),
                    )

            untrusted_bwrap = repo_root / "scripts" / "bwrap"
            untrusted_bwrap.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            untrusted_bwrap.chmod(0o755)
            with patch("core.apps.sidecar_execution.shutil.which", return_value=str(untrusted_bwrap)):
                with self.assertRaisesRegex(AppHostingError, "root-owned.*trusted system bin"):
                    prepare_confined_sidecar_launch(
                        workspace_id="default",
                        app_id="probe",
                        source_root=source_root,
                        data_root=data_root,
                        workspace_root=workspace_root,
                        sidecar=sidecar,
                        port=12345,
                        env=dict(MINIMAL_SIDECAR_ENV),
                    )

            absolute = build_http_sidecar_spec(service_id="probe", command=["/usr/bin/python3", "server.py"])
            with self.assertRaisesRegex(AppHostingError, "absolute or parent host path"):
                prepare_confined_sidecar_launch(
                    workspace_id="default",
                    app_id="probe",
                    source_root=source_root,
                    data_root=data_root,
                    workspace_root=workspace_root,
                    sidecar=absolute,
                    port=12345,
                    env=dict(MINIMAL_SIDECAR_ENV),
                )

            untrusted_node = repo_root / "scripts" / "node-runtime" / "bin" / "node"
            untrusted_node.parent.mkdir(parents=True)
            untrusted_node.write_text("", encoding="utf-8")
            untrusted_node.chmod(0o755)
            node_sidecar = build_http_sidecar_spec(
                service_id="probe",
                runtime="node",
                command=["node", "server.js"],
            )
            with (
                patch("core.apps.sidecar_execution._trusted_bubblewrap_binary", return_value="/usr/bin/bwrap"),
                patch("core.apps.sidecar_execution.shutil.which", return_value=str(untrusted_node)),
            ):
                with self.assertRaisesRegex(AppHostingError, "trusted read-only system location"):
                    prepare_confined_sidecar_launch(
                        workspace_id="default",
                        app_id="probe",
                        source_root=source_root,
                        data_root=data_root,
                        workspace_root=workspace_root,
                        sidecar=node_sidecar,
                        port=12345,
                        env=dict(MINIMAL_SIDECAR_ENV),
                    )

            real_data = workspace_root / "data" / "real-probe"
            real_data.mkdir(parents=True)
            linked_data = workspace_root / "data" / "probe"
            linked_data.symlink_to(real_data, target_is_directory=True)
            with self.assertRaisesRegex(AppHostingError, "data root cannot contain symlink components"):
                prepare_confined_sidecar_launch(
                    workspace_id="default",
                    app_id="probe",
                    source_root=source_root,
                    data_root=linked_data,
                    workspace_root=workspace_root,
                    sidecar=sidecar,
                    port=12345,
                    env=dict(MINIMAL_SIDECAR_ENV),
                )

    def test_invalid_limits_and_symlinked_workspace_data_fail_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(Path(temp_dir))
            source_root = repo_root / "apps" / "probe"
            source_root.mkdir(parents=True)
            workspace_root = repo_root / "workspaces" / "default"
            workspace_root.mkdir(parents=True)
            data_root = workspace_root / "data" / "probe"
            invalid_limits = build_http_sidecar_spec(
                service_id="probe",
                command=["python3", "server.py"],
                process_policy=build_http_sidecar_process_policy(request_concurrency=0),
            )

            with self.assertRaisesRegex(AppHostingError, "process policy is not fail-closed"):
                prepare_confined_sidecar_launch(
                    workspace_id="default",
                    app_id="probe",
                    source_root=source_root,
                    data_root=data_root,
                    workspace_root=workspace_root,
                    sidecar=invalid_limits,
                    port=12345,
                    env=dict(MINIMAL_SIDECAR_ENV),
                )

            external_data = repo_root / "external-data"
            external_data.mkdir()
            (workspace_root / "data").symlink_to(external_data, target_is_directory=True)
            valid = build_http_sidecar_spec(service_id="probe", command=["python3", "server.py"])
            with self.assertRaisesRegex(AppHostingError, "workspace data root cannot contain symlink components"):
                prepare_confined_sidecar_launch(
                    workspace_id="default",
                    app_id="probe",
                    source_root=source_root,
                    data_root=data_root,
                    workspace_root=workspace_root,
                    sidecar=valid,
                    port=12345,
                    env=dict(MINIMAL_SIDECAR_ENV),
                )

    def _repo_root(self, temp_root: Path) -> Path:
        repo_root = temp_root / "maverick"
        for name in ("core", "apps", "workspaces", "scripts"):
            (repo_root / name).mkdir(parents=True, exist_ok=True)
        (repo_root / "AGENTS.md").write_text("", encoding="utf-8")
        return repo_root

    def _assert_relay_rejects_unauthenticated_request(self, relay_path: Path) -> None:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        try:
            client.connect(str(relay_path))
            client.sendall(b"GET /health HTTP/1.0\r\nHost: sidecar.internal\r\n\r\n")
            self.assertEqual(client.recv(1024), b"")
        finally:
            client.close()

    def _assert_relay_enforces_concurrency(self, running: RunningSidecar) -> None:
        blocker = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        rejected = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        rejected.settimeout(2)
        try:
            blocker.connect(str(running.confined_launch.relay_socket))
            blocker.sendall(relay_preamble(running.confined_launch.relay_capability))
            time.sleep(0.1)
            rejected.connect(str(running.confined_launch.relay_socket))
            rejected.sendall(
                relay_preamble(running.confined_launch.relay_capability)
                + b"GET /health HTTP/1.0\r\nHost: sidecar.internal\r\n\r\n"
            )
            try:
                response = rejected.recv(1024)
            except ConnectionResetError:
                response = b""
            self.assertEqual(response, b"")
        finally:
            rejected.close()
            blocker.close()
        time.sleep(0.1)


def _descendant_pids(root_pid: int) -> set[int]:
    found: set[int] = set()
    pending = [root_pid]
    while pending:
        parent = pending.pop()
        children_path = Path(f"/proc/{parent}/task/{parent}/children")
        try:
            children = [int(value) for value in children_path.read_text(encoding="utf-8").split()]
        except (OSError, ValueError):
            continue
        for child in children:
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _probe_server_source(*, operator_secret: Path, other_workspace_secret: Path, host_port: int) -> str:
    return textwrap.dedent(
        f"""
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import json
        import os
        from pathlib import Path
        import resource
        import socket
        import subprocess

        def denied(address):
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(0.25)
            try:
                probe.connect(address)
                return False
            except OSError:
                return True
            finally:
                probe.close()

        results = {{
            "sentinel_absent": "MAVERICK_WP1_HOST_SENTINEL" not in os.environ,
            "home_absent": "HOME" not in os.environ,
            "provider_secret_absent": "OPENAI_API_KEY" not in os.environ,
            "runtime_secret_absent": "MAVERICK_RUNTIME_API_TOKEN" not in os.environ,
            "bootstrap_secret_absent": "MAVERICK_BOOTSTRAP_SECRET" not in os.environ,
            "cookie_absent": "MAVERICK_SESSION_COOKIE" not in os.environ,
            "provider_home_absent": "CODEX_HOME" not in os.environ,
            "relay_capability_absent_from_env": not any("RELAY" in key for key in os.environ),
            "sandbox_home_is_ephemeral": Path.home() == Path("/tmp/home"),
            "host_clis_absent": not any(Path(path).exists() for path in (
                "/usr/local/bin/codex", "/usr/bin/curl", "/usr/bin/git", "/bin/sh"
            )),
            "operator_home_absent": not Path({str(operator_secret)!r}).exists(),
            "other_workspace_absent": not Path({str(other_workspace_secret)!r}).exists(),
            "control_metadata_absent": not Path("/data/official-update.json").exists(),
            "technical_token_present": bool(os.environ.get("PROBE_TOKEN")),
            "memory_limit": resource.getrlimit(resource.RLIMIT_AS)[0],
            "open_files_limit": resource.getrlimit(resource.RLIMIT_NOFILE)[0],
        }}
        try:
            Path("/app/server.py").write_text("changed", encoding="utf-8")
            results["bundle_read_only"] = False
        except OSError:
            results["bundle_read_only"] = True
        try:
            Path("/outside.txt").write_text("changed", encoding="utf-8")
            results["outside_write_denied"] = False
        except OSError:
            results["outside_write_denied"] = True
        Path("/data/allowed.txt").write_text("allowed", encoding="utf-8")
        results["data_write_allowed"] = True
        routes = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]
        results["no_default_route"] = not any(line.split()[1] == "00000000" for line in routes if line.split())
        results["host_loopback_denied"] = denied(("127.0.0.1", {host_port}))
        results["metadata_denied"] = denied(("169.254.169.254", 80))
        results["internet_denied"] = denied(("1.1.1.1", 53))
        descendant = subprocess.Popen(["python3", "-c", "import time; time.sleep(60)"])
        results["descendant_started"] = descendant.poll() is None

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    self.reply({{"status": "ready"}})
                    return
                if self.path == "/probe":
                    self.reply(results)
                    return
                self.reply({{"error": "not_found"}}, status=404)

            def reply(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        ThreadingHTTPServer(("127.0.0.1", int(os.environ["PROBE_PORT"])), Handler).serve_forever()
        """
    )


if __name__ == "__main__":
    unittest.main()
