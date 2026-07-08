#!/usr/bin/env python3
"""Run an authenticated browser startup baseline against Maverick."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str, *, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/health", timeout=1) as response:  # noqa: S310 - local baseline URL.
                if response.status == 200:
                    return
        except (OSError, URLError) as error:
            last_error = error
        time.sleep(0.2)
    raise RuntimeError(f"Maverick host did not become healthy at {base_url}: {last_error}")


def _credentials(args: argparse.Namespace, env: dict[str, str]) -> tuple[str, str] | None:
    username = args.username or env.get("MAVERICK_STARTUP_USERNAME") or env.get("MAVERICK_ADMIN_USERNAME")
    password = args.password or env.get("MAVERICK_STARTUP_PASSWORD") or env.get("MAVERICK_ADMIN_PASSWORD")
    if username and password:
        return username, password
    if args.use_insecure_test_defaults:
        return "admin", "maverick"
    return None


def _print_skipped(*, reason: str, json_output: bool) -> int:
    payload = {"metric_source": "authenticated browser startup", "skipped": True, "reason": reason}
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Skipped authenticated browser startup baseline: {reason}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--base-url", help="use an already-running Maverick host")
    parser.add_argument("--port", type=int, help="local port to use when starting a host")
    parser.add_argument("--username", help="login username; defaults to MAVERICK_STARTUP_USERNAME or MAVERICK_ADMIN_USERNAME")
    parser.add_argument("--password", help="login password; defaults to MAVERICK_STARTUP_PASSWORD or MAVERICK_ADMIN_PASSWORD")
    parser.add_argument(
        "--use-insecure-test-defaults",
        action="store_true",
        help="start the local host with admin/maverick test credentials when no credentials are provided",
    )
    args = parser.parse_args()

    env = os.environ.copy()
    credentials = _credentials(args, env)
    if credentials is None:
        return _print_skipped(reason="missing credentials", json_output=args.json)
    username, password = credentials

    server: subprocess.Popen[bytes] | None = None
    base_url = args.base_url.rstrip("/") if args.base_url else ""
    if not base_url:
        port = args.port or _free_port()
        base_url = f"http://127.0.0.1:{port}"
        if args.use_insecure_test_defaults:
            env.setdefault("MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS", "1")
            env.setdefault("MAVERICK_ADMIN_USERNAME", username)
            env.setdefault("MAVERICK_ADMIN_PASSWORD", password)
        server = subprocess.Popen(
            [sys.executable, "-m", "core.api.server", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            _wait_for_health(base_url)
        except Exception:
            if server.stderr is not None:
                sys.stderr.write(server.stderr.read().decode("utf-8", errors="replace"))
            raise

    try:
        cmd = [
            "node",
            str(ROOT / "scripts" / "startup_browser_baseline.mjs"),
            "--base-url",
            base_url,
            "--username",
            username,
            "--password",
            password,
        ]
        if args.json:
            cmd.append("--json")
        completed = subprocess.run(cmd, cwd=ROOT, env=env, check=False)
        return int(completed.returncode)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
