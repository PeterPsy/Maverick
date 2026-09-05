#!/usr/bin/env python3
"""Run the authenticated PWA shell and Settings cache smoke against a local host."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(
    port: int,
    server: subprocess.Popen[bytes],
    timeout_seconds: float = 60.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        return_code = server.poll()
        if return_code is not None:
            raise RuntimeError(f"Maverick host exited before becoming healthy ({return_code}).")
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except (OSError, URLError) as error:
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f"Maverick host did not become healthy: {last_error}")


def _stop_server(server: subprocess.Popen[bytes]) -> None:
    if server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def _local_environment(root: Path, username: str, password: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("MAVERICK_SECRET_KEY_FILE", None)
    env.update({
        "MAVERICK_ADMIN_PASSWORD": password,
        "MAVERICK_ADMIN_USERNAME": username,
        "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
        "MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT": str(root / "bootstrap-secrets"),
        "MAVERICK_JSON_CONTROL_STORE_ROOT": str(root / "control-plane"),
        "MAVERICK_SECRET_STORE_KEY": "maverick-local-secret-store",
        "MAVERICK_SIDECAR_ORIGIN_MODE": "local",
    })
    no_proxy = env.get("NO_PROXY", env.get("no_proxy", ""))
    local_hosts = "127.0.0.1,localhost,.localhost"
    env["NO_PROXY"] = f"{no_proxy},{local_hosts}" if no_proxy else local_hosts
    return env


def _create_disposable_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    for name in ("AGENTS.md", "apps", "core", "docs", "packages", "scripts"):
        (repository / name).symlink_to(ROOT / name, target_is_directory=(ROOT / name).is_dir())
    (repository / "workspaces").mkdir()
    return repository


def _run_browser(base_url: str, username: str, password: str, env: dict[str, str]) -> int:
    command = [
        "node",
        str(ROOT / "scripts" / "pwa_shell_cache_smoke.mjs"),
        "--base-url",
        base_url,
        "--engine",
        "chromium",
        "--password",
        password,
        "--require-browser",
        "--username",
        username,
    ]
    if env.get("MAVERICK_PWA_SMOKE_APP_READ_MODELS") == "1":
        command.append("--app-read-models")
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="use an already-running host instead of starting one")
    parser.add_argument("--password", default="maverick", help="test login password")
    parser.add_argument("--port", type=int, help="local server port")
    parser.add_argument("--username", default="admin", help="test login username")
    parser.add_argument("--app-read-models", action="store_true", help="test approved display adapters on a disposable host only")
    args = parser.parse_args()
    if args.app_read_models and args.base_url:
        parser.error("--app-read-models requires a disposable host; live rollout flags are not modified")
    if args.base_url:
        return _run_browser(args.base_url.rstrip("/"), args.username, args.password, os.environ.copy())

    with tempfile.TemporaryDirectory(prefix="maverick-pwa-smoke-") as temporary:
        temporary_root = Path(temporary)
        repository_root = _create_disposable_repository(temporary_root)
        env = _local_environment(temporary_root, args.username, args.password)
        if args.app_read_models:
            env["MAVERICK_PWA_SMOKE_APP_READ_MODELS"] = "1"
            env["MAVERICK_FEATURE_PWA_DATA_CACHE"] = "1"
            for app in ("CALENDAR", "CHAT", "CRM", "MAIL", "FITNESS_COACH"):
                env[f"MAVERICK_FEATURE_PWA_APP_CACHE_{app}"] = "1"
        port = args.port or _free_port()
        log_path = temporary_root / "host.stderr.log"
        with log_path.open("wb") as host_log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "pwa_smoke_host.py"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--repository-root",
                    str(repository_root),
                ],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=host_log,
            )
            try:
                try:
                    _wait_for_health(port, server)
                except Exception:
                    _stop_server(server)
                    host_log.flush()
                    sys.stderr.write(log_path.read_text(encoding="utf-8", errors="replace"))
                    raise
                return _run_browser(
                    f"http://maverick.localhost:{port}",
                    args.username,
                    args.password,
                    env,
                )
            finally:
                _stop_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
