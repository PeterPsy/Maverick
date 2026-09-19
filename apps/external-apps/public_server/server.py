"""Bounded HTTP/1.0 Unix listener for the dedicated public ingress."""
import argparse
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import resource
import signal
from socketserver import ThreadingMixIn, UnixStreamServer
import sys
from threading import BoundedSemaphore

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_server.serving import PublicRuntime


class PublicServer(ThreadingMixIn, UnixStreamServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = 32

    def __init__(self, address, runtime):
        self.runtime = runtime
        self.slots = BoundedSemaphore(32)
        super().__init__(str(address), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "ExternalApps"
    sys_version = ""
    timeout = 5
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args):
        pass  # Never log cookies, source/workspace paths, arbitrary request targets.

    def do_GET(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0") != "0":
            result = self.server.runtime.error(400, "invalid_request")
        else:
            result = self.server.runtime.response(self.command, hosts[0], self.path,
                                                  {name.lower(): value for name, value in self.headers.items()})
        code, headers, content = result
        self.send_response(code)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    do_HEAD = do_GET
    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
    do_PATCH = do_GET
    do_OPTIONS = do_GET
    do_TRACE = do_GET
    do_CONNECT = do_GET


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--projection", required=True)
    parser.add_argument("--mounts", required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    os.umask(0o007)
    runtime = PublicRuntime(domain=args.domain, mounts=json.loads(args.mounts), projection=Path(args.projection))
    socket_path = Path(args.socket)
    if socket_path.exists():
        raise SystemExit("listener_path_in_use")
    server = PublicServer(socket_path, runtime)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        socket_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
