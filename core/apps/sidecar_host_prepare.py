"""Bounded host-only preparation for a fresh confined sidecar launch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from core.apps.errors import AppHostingError
from core.apps.models import HttpSidecarHostPrepareSpec
from core.shared.repository import installation_paths


MAX_PREPARE_ENVIRONMENT_BYTES = 256 * 1024
MAX_PREPARE_VALUE_BYTES = 64 * 1024


def run_sidecar_host_prepare(
    source_root: Path,
    declaration: HttpSidecarHostPrepareSpec,
    *,
    payload: dict[str, object],
) -> dict[str, str]:
    """Run one declared hook and return only its allowlisted environment projection."""
    source = Path(source_root).resolve(strict=True)
    entrypoint = source / declaration.entrypoint
    try:
        resolved_entrypoint = entrypoint.resolve(strict=True)
        resolved_entrypoint.relative_to(source)
    except (OSError, ValueError) as error:
        raise AppHostingError("Sidecar host preparation entrypoint is unavailable.") from error
    repository_root = str(installation_paths(start_path=source).repository_root)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = (
        repository_root
        if not environment.get("PYTHONPATH")
        else f"{repository_root}{os.pathsep}{environment['PYTHONPATH']}"
    )
    try:
        result = subprocess.run(
            [sys.executable, str(resolved_entrypoint)],
            input=json.dumps(payload, ensure_ascii=True),
            cwd=source,
            env=environment,
            text=True,
            capture_output=True,
            timeout=declaration.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise AppHostingError("Sidecar host preparation timed out.") from error
    if result.returncode != 0:
        raise AppHostingError("Sidecar host preparation failed.")
    try:
        response = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise AppHostingError("Sidecar host preparation returned invalid JSON.") from error
    if (
        not isinstance(response, dict)
        or set(response) != {"ok", "environment"}
        or response.get("ok") is not True
        or not isinstance(response.get("environment"), dict)
        or set(response["environment"]) != set(declaration.environment_keys)
    ):
        raise AppHostingError("Sidecar host preparation returned an invalid projection.")
    projected: dict[str, str] = {}
    total_bytes = 0
    for key in declaration.environment_keys:
        value = response["environment"].get(key)
        if not isinstance(value, str) or "\x00" in value:
            raise AppHostingError("Sidecar host preparation returned an invalid value.")
        encoded_size = len(value.encode("utf-8"))
        if encoded_size > MAX_PREPARE_VALUE_BYTES:
            raise AppHostingError("Sidecar host preparation value exceeds its limit.")
        total_bytes += encoded_size
        projected[key] = value
    if total_bytes > MAX_PREPARE_ENVIRONMENT_BYTES:
        raise AppHostingError("Sidecar host preparation projection exceeds its limit.")
    return projected


__all__ = ["run_sidecar_host_prepare"]
