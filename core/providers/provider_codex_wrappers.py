"""Runtime-local Maverick CLI wrapper management for Codex sessions."""

from __future__ import annotations

from pathlib import Path


def refresh_workspace_maverick_wrappers(repository_root: Path) -> list[Path]:
    """Refresh existing runtime-local Maverick CLI wrappers in workspace sessions."""
    refreshed: list[Path] = []
    sessions_root = Path(repository_root) / "workspaces"
    if not sessions_root.is_dir():
        return refreshed
    for wrapper in sessions_root.glob("*/runtime/sessions/*/bin/maverick"):
        try:
            current = wrapper.read_text(encoding="utf-8") if wrapper.is_file() else ""
            source = _workspace_maverick_wrapper_source()
            if current == source:
                continue
            _write_workspace_maverick_wrapper(wrapper)
            refreshed.append(wrapper)
        except OSError:
            continue
    return refreshed


def _write_workspace_maverick_wrapper(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_workspace_maverick_wrapper_source(), encoding="utf-8")
    path.chmod(0o755)


def _workspace_maverick_wrapper_source() -> str:
    """Return the workspace-local Maverick CLI wrapper installed into runtime/bin."""
    return """#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request


def main(argv):
    if not argv or argv in (["--help"], ["-h"]):
        print("Usage: maverick {apps|core|app|sdk} ...")
        print("       maverick apps list --json")
        print("       maverick core cli list --json")
        print("       maverick app <app_id> frontend build --json")
        print("       maverick core cli run core.app-sdk.create --app-id <app_id> --template-id <id> --json")
        return 0
    if argv[:2] == ["sdk", "templates"]:
        return call_sdk({"action": "templates"})
    if argv[:2] == ["sdk", "docs"]:
        return call_sdk({"action": "docs"}, text_field="content")
    return call_cli(argv)


def runtime_auth_headers():
    token = os.environ.get("MAVERICK_RUNTIME_API_TOKEN", "")
    if not token:
        print("maverick: MAVERICK_RUNTIME_API_TOKEN is not set", file=sys.stderr)
        return None
    return {"Content-Type": "application/json", "Authorization": "Bearer " + token}


def call_sdk(payload, text_field=None):
    base_url = os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014").rstrip("/")
    headers = runtime_auth_headers()
    if headers is None:
        return 1
    request = urllib.request.Request(
        base_url + "/api/app-sdk",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return print_response(request, text_field=text_field)


def call_cli(argv):
    base_url = os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014").rstrip("/")
    headers = runtime_auth_headers()
    if headers is None:
        return 1
    request = urllib.request.Request(
        base_url + "/api/runtime/cli",
        data=json.dumps({"argv": argv, "effective_mode": os.environ.get("MAVERICK_EFFECTIVE_MODE", "sandbox")}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return print_response(request)


def print_response(request, text_field=None):
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        sys.stderr.write(error.read().decode("utf-8") + "\\n")
        return 1
    if text_field:
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            print(body)
            return 0
        print(decoded.get(text_field, ""))
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""
