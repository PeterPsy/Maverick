"""G2 real bubblewrap filesystem, network, relay, and cleanup proof."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
import unittest


_PAYLOAD = r'''
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

host_port = int(sys.argv[1])
results = {
    "sentinel_absent": "MAVERICK_G2_HOST_SENTINEL" not in os.environ,
    "home_absent": "HOME" not in os.environ,
    "operator_home_absent": not Path("/operator-home/proof-secret").exists(),
    "other_workspace_absent": not Path("/other-workspace/proof-secret").exists(),
}

try:
    Path("/bundle/read-only.txt").write_text("changed", encoding="utf-8")
    results["bundle_read_only"] = False
except OSError:
    results["bundle_read_only"] = True

try:
    Path("/outside.txt").write_text("denied", encoding="utf-8")
    results["outside_write_denied"] = False
except OSError:
    results["outside_write_denied"] = True

Path("/data/allowed.txt").write_text("allowed", encoding="utf-8")
results["data_write_allowed"] = Path("/data/allowed.txt").read_text(encoding="utf-8") == "allowed"

routes = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]
results["no_default_route"] = not any(line.split()[1] == "00000000" for line in routes if line.split())

def connect_denied(address):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.4)
    try:
        probe.connect(address)
        return False
    except OSError:
        return True
    finally:
        probe.close()

results["host_loopback_denied"] = connect_denied(("127.0.0.1", host_port))
results["internet_denied"] = connect_denied(("1.1.1.1", 53))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ready"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

health = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
threading.Thread(target=health.serve_forever, daemon=True).start()

relay_path = Path("/relay/sidecar.sock")
relay_path.unlink(missing_ok=True)
relay = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
relay.bind(str(relay_path))
os.chmod(relay_path, 0o600)
relay.listen(1)

descendant = subprocess.Popen(["/usr/bin/sleep", "60"])
results["descendant_pid"] = descendant.pid
Path("/relay/result.json").write_text(json.dumps(results), encoding="utf-8")

client, _ = relay.accept()
request = client.recv(8192)
upstream = socket.create_connection(("127.0.0.1", health.server_port), timeout=2)
upstream.sendall(request)
while True:
    chunk = upstream.recv(8192)
    if not chunk:
        break
    client.sendall(chunk)
upstream.close()
client.close()

while True:
    time.sleep(1)
'''


def _bubblewrap_binary(candidate: str | None = None) -> str:
    resolved = shutil.which("bwrap") if candidate is None else shutil.which(candidate)
    if not resolved:
        raise RuntimeError("bubblewrap is required for sandbox-required sidecars")
    return resolved


class SidecarConfinementDecisionProof(unittest.TestCase):
    def test_bubblewrap_filesystem_network_relay_and_cleanup(self) -> None:
        bwrap = _bubblewrap_binary()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "bundle"
            data = root / "data"
            relay_dir = root / "relay"
            operator_home = root / "operator-home"
            other_workspace = root / "other-workspace"
            sandbox_root = root / "sandbox-root"
            for directory in (bundle, data, relay_dir, operator_home, other_workspace):
                directory.mkdir()
            for relative in ("usr", "bin", "lib", "lib64", "proc", "dev", "tmp", "bundle", "data", "relay"):
                (sandbox_root / relative).mkdir(parents=True, exist_ok=True)
            (sandbox_root / "proof.py").touch()
            (bundle / "read-only.txt").write_text("verified", encoding="utf-8")
            (operator_home / "proof-secret").write_text("operator-secret", encoding="utf-8")
            (other_workspace / "proof-secret").write_text("workspace-secret", encoding="utf-8")
            payload_path = root / "payload.py"
            payload_path.write_text(_PAYLOAD, encoding="utf-8")

            host_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            host_listener.bind(("127.0.0.1", 0))
            host_listener.listen(1)
            self.addCleanup(host_listener.close)

            command = [
                bwrap,
                "--die-with-parent",
                "--unshare-user",
                "--uid",
                "0",
                "--gid",
                "0",
                "--unshare-net",
                "--unshare-ipc",
                "--unshare-uts",
                "--clearenv",
                "--setenv",
                "PATH",
                "/usr/bin:/bin",
                "--ro-bind",
                str(sandbox_root),
                "/",
                "--ro-bind",
                "/usr",
                "/usr",
                "--ro-bind",
                "/bin",
                "/bin",
                "--ro-bind",
                "/lib",
                "/lib",
                "--ro-bind",
                "/lib64",
                "/lib64",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--ro-bind",
                str(bundle),
                "/bundle",
                "--bind",
                str(data),
                "/data",
                "--bind",
                str(relay_dir),
                "/relay",
                "--ro-bind",
                str(payload_path),
                "/proof.py",
                "/usr/bin/python3",
                "/proof.py",
                str(host_listener.getsockname()[1]),
            ]
            env = {"MAVERICK_G2_HOST_SENTINEL": "must-not-cross", "HOME": str(operator_home)}
            process = subprocess.Popen(
                command,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            self.addCleanup(self._terminate, process)

            result_path = relay_dir / "result.json"
            relay_path = relay_dir / "sidecar.sock"
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not (result_path.is_file() and relay_path.exists()):
                if process.poll() is not None:
                    _stdout, stderr = process.communicate(timeout=1)
                    self.fail(f"bubblewrap proof exited early: {stderr}")
                time.sleep(0.05)
            self.assertTrue(result_path.is_file(), "sandbox proof did not publish results")
            self.assertTrue(relay_path.exists(), "sandbox proof did not publish its Unix relay")

            results = json.loads(result_path.read_text(encoding="utf-8"))
            for key, value in results.items():
                if key != "descendant_pid":
                    self.assertTrue(value, key)
            self.assertEqual(stat.S_IMODE(relay_path.stat().st_mode), 0o600)

            relay = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            relay.settimeout(3)
            relay.connect(str(relay_path))
            relay.sendall(b"GET /api/ready HTTP/1.0\r\nHost: sidecar.internal\r\n\r\n")
            response = b""
            while True:
                chunk = relay.recv(8192)
                if not chunk:
                    break
                response += chunk
            relay.close()
            self.assertIn(b"200 OK", response)
            self.assertIn(b'{"status":"ready"}', response)

            descendant_pid = int(results["descendant_pid"])
            self._terminate(process)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and Path(f"/proc/{descendant_pid}").exists():
                time.sleep(0.05)
            self.assertFalse(Path(f"/proc/{descendant_pid}").exists(), "sandbox descendant survived cleanup")

    def test_missing_bubblewrap_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "bubblewrap is required"):
            _bubblewrap_binary("maverick-definitely-missing-bwrap")

    def _terminate(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
