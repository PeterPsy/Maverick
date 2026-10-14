"""Domain fixtures extracted without changing assertions."""

from __future__ import annotations
from pathlib import Path
import textwrap

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
            "sentinel_absent": "LOOPINO_WP1_HOST_SENTINEL" not in os.environ,
            "home_absent": "HOME" not in os.environ,
            "provider_secret_absent": "OPENAI_API_KEY" not in os.environ,
            "runtime_secret_absent": "LOOPINO_RUNTIME_API_TOKEN" not in os.environ,
            "bootstrap_secret_absent": "LOOPINO_BOOTSTRAP_SECRET" not in os.environ,
            "cookie_absent": "LOOPINO_SESSION_COOKIE" not in os.environ,
            "provider_home_absent": "CODEX_HOME" not in os.environ,
            "relay_capability_absent_from_env": not any("RELAY" in key for key in os.environ),
            "sandbox_home_is_ephemeral": Path.home() == Path("/tmp/home"),
            "host_clis_absent": not any(Path(path).exists() for path in (
                "/usr/local/bin/codex", "/usr/bin/curl", "/usr/bin/git", "/bin/sh"
            )),
            "operator_home_absent": not Path({str(operator_secret)!r}).exists(),
            "other_workspace_absent": not Path({str(other_workspace_secret)!r}).exists(),
            "control_metadata_absent": not Path("/data/official-update.json").exists(),
            "diagnostic_capability_present": os.environ.get("LOOPINO_SIDECAR_STATUS_FILE") == "/run/loopino/sidecar-status.json",
            "diagnostic_parent_is_hidden": not Path("/run/loopino/official-update.json").exists(),
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
        status_file = os.environ.get("LOOPINO_SIDECAR_STATUS_FILE", "")
        if status_file:
            Path(status_file).write_text(
                json.dumps({{"state": "ready", "source": "confined-sidecar"}}),
                encoding="utf-8",
            )
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
