#!/usr/bin/env python3
"""Start a disposable-root Core host for the authenticated PWA browser smoke."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from core.api.asgi_application import PlatformAsgiHost
from core.api.backend_recovery import start_backend_restart_recovery
from core.api.background_hooks import start_background_hook_scheduler
from core.api.platform_state import bootstrap_platform_state
from core.api.sidecar_control import start_sidecar_control_server
from core.api.sidecar_prewarm import start_declared_sidecar_prewarms
from core.model_access.broker import start_model_access_broker_server
from core.shared.entrypoints import EntrypointShutdownController


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--repository-root", required=True, type=Path)
    args = parser.parse_args()

    state = bootstrap_platform_state(start_path=args.repository_root)
    shutdown = EntrypointShutdownController()
    start_model_access_broker_server(state, shutdown_controller=shutdown)
    prewarm_threads = start_declared_sidecar_prewarms(
        state,
        trigger="core_start",
        shutdown_controller=shutdown,
    )
    start_backend_restart_recovery(state, after_threads=prewarm_threads)
    start_background_hook_scheduler(state, shutdown_controller=shutdown)
    start_sidecar_control_server(state, shutdown_controller=shutdown)
    application = PlatformAsgiHost(state, shutdown_controller=shutdown)
    try:
        uvicorn.run(application, host=args.host, port=args.port, log_level="warning")
    finally:
        shutdown.begin_shutdown()


if __name__ == "__main__":
    main()
