"""Atomic, redaction-safe OpenDesign repair-state persistence."""

from __future__ import annotations

from pathlib import Path
import re
import time

from opendesign_artifact import write_canonical_json


_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}")
_STATES = {"idle", "repairing", "failed"}


def write_repair_state(
    data_root: Path,
    *,
    state: str,
    error_code: str | None = None,
    phase: str | None = None,
    observed_at_epoch_ms: int | None = None,
) -> Path:
    """Write one bounded state record without persisting exception details."""
    if state not in _STATES:
        raise ValueError("Unsupported OpenDesign repair state")
    generation_root = Path(data_root) / "opendesign"
    generation_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = generation_root / "repair-state.json"
    write_canonical_json(
        path,
        {
            "schema_version": "1",
            "state": state,
            "observed_at_epoch_ms": (
                int(time.time() * 1000)
                if observed_at_epoch_ms is None
                else max(0, int(observed_at_epoch_ms))
            ),
            "error_code": _safe_identifier(error_code, fallback="artifact_repair_failed")
            if state == "failed"
            else None,
            "phase": _safe_identifier(phase, fallback="artifact_repair")
            if state == "failed"
            else None,
        },
    )
    path.chmod(0o600)
    return path


def failure_identity(
    error: BaseException,
    *,
    default_code: str = "artifact_repair_failed",
    default_phase: str = "artifact_repair",
) -> tuple[str, str]:
    """Return only public identifiers from a repair/audit exception."""
    return (
        _safe_identifier(getattr(error, "code", None), fallback=default_code),
        _safe_identifier(getattr(error, "phase", None), fallback=default_phase),
    )


def _safe_identifier(value: object, *, fallback: str) -> str:
    text = str(value or "")
    return text if _IDENTIFIER.fullmatch(text) is not None else fallback
