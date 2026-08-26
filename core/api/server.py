"""Small WSGI servers for the hosted Maverick core and rescue surfaces."""

from __future__ import annotations

import argparse
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from core.api.backend_recovery import start_backend_restart_recovery
from core.api.background_hooks import start_background_hook_scheduler
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.api.rescue_host import RescueHost
from core.api.sidecar_prewarm import start_declared_sidecar_prewarms
from core.api.sidecar_control import start_sidecar_control_server
from core.shared.entrypoints import EntrypointShutdownController


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    """Serve WSGI requests concurrently for light local hosting."""

    daemon_threads = True


def run_platform_server(*, host: str, port: int) -> None:
    """Run the main platform host."""
    state = bootstrap_platform_state()
    shutdown_controller = EntrypointShutdownController()
    prewarm_threads = start_declared_sidecar_prewarms(
        state,
        trigger="core_start",
        shutdown_controller=shutdown_controller,
    )
    start_backend_restart_recovery(state, after_threads=prewarm_threads)
    start_background_hook_scheduler(state, shutdown_controller=shutdown_controller)
    start_sidecar_control_server(state, shutdown_controller=shutdown_controller)
    app = PlatformHost(state, shutdown_controller=shutdown_controller)
    try:
        with make_server(host, port, app, server_class=ThreadedWSGIServer) as server:
            server.serve_forever()
    finally:
        shutdown_controller.begin_shutdown()


def run_rescue_server(*, host: str, port: int) -> None:
    """Run the independent rescue host."""
    with make_server(host, port, RescueHost(), server_class=ThreadedWSGIServer) as server:
        server.serve_forever()


def main() -> None:
    """Run the selected Maverick HTTP host."""
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
