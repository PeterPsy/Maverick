"""Helpers for invoking app entrypoint scripts through a deterministic JSON contract."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any


def run_json_entrypoint(
    entrypoint_path: str | Path,
    *,
    payload: dict[str, Any],
    cwd: str | Path,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Invoke one Python entrypoint script with JSON stdin and JSON stdout."""
    process = subprocess.run(
        ["python3", str(entrypoint_path)],
        input=json.dumps(payload, ensure_ascii=True),
        text=True,
        capture_output=True,
        cwd=str(cwd),
        timeout=timeout_seconds,
        check=False,
    )
    if process.returncode != 0:
        stderr = (process.stderr or "").strip()
        raise RuntimeError(
            f"Entrypoint `{entrypoint_path}` failed with exit code {process.returncode}: {stderr or 'no stderr'}"
        )
    try:
        result = json.loads(process.stdout or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Entrypoint `{entrypoint_path}` did not emit valid JSON.") from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Entrypoint `{entrypoint_path}` did not emit a JSON object.")
    return result
