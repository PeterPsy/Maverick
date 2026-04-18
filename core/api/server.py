"""Small WSGI servers for the hosted Maverick v3 core and rescue surfaces."""

from __future__ import annotations

import argparse
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.rescue_host import RescueHost


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    """Serve WSGI requests concurrently for light local hosting."""

    daemon_threads = True


def run_platform_server(*, host: str, port: int) -> None:
    """Run the main platform host."""
    state = bootstrap_platform_state()
    app = PlatformHost(state)
    with make_server(host, port, app, server_class=ThreadedWSGIServer) as server:
        server.serve_forever()


def run_rescue_server(*, host: str, port: int) -> None:
    """Run the independent rescue host."""
    with make_server(host, port, RescueHost(), server_class=ThreadedWSGIServer) as server:
        server.serve_forever()


def main() -> None:
    """Run the selected Maverick v3 HTTP host."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", choices=("core", "rescue"), default="core")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8014)
    args = parser.parse_args()
    if args.service == "rescue":
        run_rescue_server(host=args.host, port=args.port)
        return
    run_platform_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
