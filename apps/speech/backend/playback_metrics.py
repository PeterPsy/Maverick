"""Redaction-safe browser speech playback metrics."""

from __future__ import annotations

from datetime import UTC, datetime
import math
from pathlib import Path
import re

from errors import SpeechValidationError
from store import upsert_job


PLAYBACK_METRIC_FIELDS = (
    "tap_to_request_ms",
    "backend_entrypoint_ms",
    "upstream_connect_ms",
    "upstream_headers_ms",
    "upstream_first_audio_byte_ms",
    "browser_first_chunk_ms",
    "tap_to_audio_playing_ms",
)
PLAYBACK_MODES = {"buffered", "pcm-stream"}
PLAYBACK_OUTCOMES = {"playing", "completed", "cancelled", "failed"}


def record_playback_metrics_payload(data_root: Path, body: dict) -> dict:
    playback_id = _bounded_identifier(body.get("playback_id"), field="playback_id", max_length=96)
    mode = str(body.get("mode") or "").strip().lower()
    if mode not in PLAYBACK_MODES:
        raise SpeechValidationError(
            "Unsupported playback metric mode.",
            operation="record_playback_metrics",
            allowed_values={"mode": sorted(PLAYBACK_MODES)},
        )
    outcome = str(body.get("outcome") or "playing").strip().lower()
    if outcome not in PLAYBACK_OUTCOMES:
        raise SpeechValidationError(
            "Unsupported playback metric outcome.",
            operation="record_playback_metrics",
            allowed_values={"outcome": sorted(PLAYBACK_OUTCOMES)},
        )
    metrics = body.get("metrics") if isinstance(body.get("metrics"), dict) else body
    observed_at = datetime.now(tz=UTC).isoformat()
    job = {
        "job_id": f"playback_{playback_id}",
        "kind": "tts_playback",
        "created_at": observed_at,
        "playback_id": playback_id,
        "mode": mode,
        "outcome": outcome,
        "retention": "metadata_only",
    }
    generation_id = _optional_identifier(metrics.get("generation_id"), max_length=256)
    if generation_id:
        job["generation_id"] = generation_id
    if "underrun_count" in metrics:
        job["underrun_count"] = _bounded_count(metrics.get("underrun_count"))
    failure_code = _optional_identifier(body.get("failure_code"), max_length=64)
    if failure_code:
        job["failure_code"] = failure_code
    for field in PLAYBACK_METRIC_FIELDS:
        value = _bounded_milliseconds(metrics.get(field))
        if value is not None:
            job[field] = value
    upsert_job(data_root, job)
    return {
        "recorded": True,
        "playback_id": playback_id,
        "outcome": outcome,
    }


def _bounded_identifier(value: object, *, field: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length or not re.fullmatch(r"[A-Za-z0-9._:-]+", text):
        raise SpeechValidationError(
            f"{field} must be a bounded identifier.",
            operation="record_playback_metrics",
            expected_fields=[field],
        )
    return text


def _optional_identifier(value: object, *, max_length: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length or not re.fullmatch(r"[A-Za-z0-9._:-]+", text):
        return ""
    return text


def _bounded_milliseconds(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0 or parsed > 3_600_000:
        return None
    return round(parsed, 3)


def _bounded_count(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(parsed, 100_000))
