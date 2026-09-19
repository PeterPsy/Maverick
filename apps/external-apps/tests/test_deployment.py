"""Deployment templates: no live nginx reload, service install, or public DNS."""
import http.client
import os
from pathlib import Path
import shutil
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

from support import APP_ROOT


DEPLOYMENT = APP_ROOT / "deployment"


class DeploymentContractTests(unittest.TestCase):
    def test_unit_does_not_manage_core_or_load_its_secrets(self):
        unit = (DEPLOYMENT / "maverick-external-apps.service.example").read_text()
        self.assertNotIn("maverick-core.service", unit)
        self.assertNotIn("EnvironmentFile=", unit)
        self.assertIn("KillMode=mixed", unit)
        self.assertIn("NoNewPrivileges=yes", unit)
        self.assertIn("ProtectSystem=strict", unit)
        writes = [line for line in unit.splitlines() if line.startswith("ReadWritePaths=")]
        self.assertEqual(len(writes), 4)
        self.assertTrue(all(line.endswith(".lock") for line in writes[1:]))


class Upstream(socketserver.StreamRequestHandler):
    def handle(self):
        request = self.rfile.readline()
        headers = {}
        while line := self.rfile.readline().strip():
            name, value = line.decode().split(":", 1)
            headers[name.lower()] = value.strip()
        self.server.received.append(headers)
        status = b"304 Not Modified" if headers.get("if-none-match") == '"release"' else b"200 OK"
        body = b"public bytes" if status.startswith(b"200") else b""
        response = (b"HTTP/1.0 " + status + b"\r\nContent-Length: " + str(len(body)).encode()
                    + b"\r\nCache-Control: no-cache, must-revalidate\r\nETag: \"release\""
                    + b"\r\nX-External-Release: rel_test\r\nSet-Cookie: must-not-escape=yes"
                    + b"\r\nX-Accel-Redirect: /private\r\n\r\n")
        self.wfile.write(response + (b"" if request.startswith(b"HEAD ") else body))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(os.environ.get("EXTERNAL_APPS_INGRESS_TEST") == "1", "opt-in foreground nginx proof")
class NginxIngressTests(unittest.TestCase):
    def test_shared_ingress_strips_credentials_revalidates_and_fails_closed(self):
        nginx = shutil.which("nginx") or "/usr/sbin/nginx"
        self.assertTrue(Path(nginx).is_file(), "nginx required for explicit ingress proof")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain, tls = free_port(), free_port()
            cert, key = root / "cert.pem", root / "key.pem"
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", "/CN=apps.example.com", "-addext",
                "subjectAltName=DNS:apps.example.com,DNS:*.apps.example.com,DNS:private.example.net",
                "-keyout", str(key), "-out", str(cert),
            ], capture_output=True, check=True, timeout=15)
            template = (DEPLOYMENT / "nginx.example.conf").read_text()
            template = (template.replace("listen 80;", f"listen 127.0.0.1:{plain};")
                        .replace("listen [::]:80;", "")
                        .replace("listen 443 ssl;", f"listen 127.0.0.1:{tls} ssl;")
                        .replace("listen [::]:443 ssl;", "")
                        .replace("/etc/ssl/external-apps/fullchain.pem", str(cert))
                        .replace("/etc/ssl/external-apps/privkey.pem", str(key))
                        .replace("/run/maverick-external-apps-listener/public.sock", str(root / "public.sock")))
            # Existing private/default hosts must not be taken over by the template.
            private = (f"server {{ listen 127.0.0.1:{plain} default_server; "
                       f"listen 127.0.0.1:{tls} ssl default_server; server_name private.example.net; "
                       f"ssl_certificate {cert}; ssl_certificate_key {key}; "
                       'return 200 "private marker"; }')
            config = root / "nginx.conf"
            config.write_text(f"pid {root}/nginx.pid; error_log {root}/error.log; "
                              "events { worker_connections 64; } http { access_log off; "
                              f"client_body_temp_path {root}/body; proxy_temp_path {root}/proxy; "
                              + private + template + " }")
            args = [nginx, "-p", str(root), "-c", str(config)]
            checked = subprocess.run(args + ["-t"], capture_output=True, text=True, timeout=5)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            context = ssl.create_default_context(cafile=str(cert))

            def request(host="sample.apps.example.com", path="/", method="GET", headers=None, secure=True):
                with socket.create_connection(("127.0.0.1", tls if secure else plain), timeout=3) as raw:
                    with (context.wrap_socket(raw, server_hostname=host) if secure else raw) as sock:
                        extra = "".join(f"{name}: {value}\r\n" for name, value in (headers or {}).items())
                        sock.sendall(f"{method} {path} HTTP/1.0\r\nHost: {host}\r\n{extra}\r\n".encode())
                        response = http.client.HTTPResponse(sock, method=method)
                        response.begin()
                        return response.status, dict(response.getheaders()), response.read()

            with socketserver.UnixStreamServer(str(root / "public.sock"), Upstream) as upstream:
                upstream.received = []
                thread = threading.Thread(target=upstream.serve_forever)
                thread.start()
                try:
                    with subprocess.Popen(args + ["-g", "daemon off; master_process off;"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as process:
                        try:
                            deadline = time.monotonic() + 5
                            while time.monotonic() < deadline and process.poll() is None:
                                try:
                                    with socket.create_connection(("127.0.0.1", tls), timeout=.1):
                                        break
                                except OSError:
                                    time.sleep(.05)
                            self.assertIsNone(process.poll(), (root / "error.log").read_text())
                            self.assertEqual(request("private.example.net")[2], b"private marker")
                            with self.assertRaises(http.client.RemoteDisconnected):
                                request(secure=False)
                            status, headers, body = request(headers={
                                "Cookie": "private=value", "Authorization": "Bearer secret",
                                "Proxy-Authorization": "Basic secret", "X-Private-Token": "secret",
                                "Accept": "text/html", "Accept-Encoding": "gzip",
                            })
                            self.assertEqual((status, body), (200, b"public bytes"))
                            self.assertEqual(headers["X-External-Release"], "rel_test")
                            self.assertNotIn("Set-Cookie", headers)
                            self.assertNotIn("Content-Encoding", headers)
                            self.assertEqual(set(upstream.received[-1]), {"host", "accept", "connection"})
                            self.assertEqual(request(method="HEAD")[2], b"")
                            self.assertEqual(request(headers={"If-None-Match": '"release"'})[0], 304)
                            self.assertEqual(len(upstream.received), 3)
                            self.assertEqual(request(method="POST")[0], 403)
                            self.assertEqual(len(upstream.received), 3)
                            # A lost public listener must not reach the private default host.
                            (root / "public.sock").unlink()
                            status, headers, body = request()
                            self.assertEqual(status, 503)
                            self.assertEqual(headers["Cache-Control"], "no-store")
                            self.assertNotIn(b"private marker", body)
                            self.assertEqual(request("private.example.net")[2], b"private marker")
                        finally:
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                finally:
                    upstream.shutdown()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
