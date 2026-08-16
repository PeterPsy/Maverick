"""Opaque composite snapshots for event archives and turn fallbacks."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json

from core.runtime.errors import RuntimeTranscriptValidationError


SNAPSHOT_PREFIX = "runtime.transcript.snapshot.v1."


@dataclass(frozen=True)
class RuntimeTranscriptSnapshot:
    session_id: str
    event_position: int
    event_id: str | None
    turn_position: int
    turn_id: str | None


def encode_runtime_transcript_snapshot(snapshot: RuntimeTranscriptSnapshot) -> str:
    payload = {
        "s": snapshot.session_id,
        "ep": snapshot.event_position,
        "ei": snapshot.event_id,
        "tp": snapshot.turn_position,
        "ti": snapshot.turn_id,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"{SNAPSHOT_PREFIX}{encoded}"


def decode_runtime_transcript_snapshot(value: str, *, session_id: str) -> RuntimeTranscriptSnapshot:
    normalized = str(value or "").strip()
    if not normalized.startswith(SNAPSHOT_PREFIX):
        raise RuntimeTranscriptValidationError("invalid_snapshot_cursor")
    encoded = normalized[len(SNAPSHOT_PREFIX) :]
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
        snapshot = RuntimeTranscriptSnapshot(
            session_id=str(payload["s"]),
            event_position=int(payload["ep"]),
            event_id=_optional_identifier(payload.get("ei")),
            turn_position=int(payload["tp"]),
            turn_id=_optional_identifier(payload.get("ti")),
        )
    except (binascii.Error, KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeTranscriptValidationError("invalid_snapshot_cursor") from error
    if snapshot.session_id != session_id:
        raise RuntimeTranscriptValidationError("invalid_snapshot_cursor")
    if (snapshot.event_position == -1) != (snapshot.event_id is None):
        raise RuntimeTranscriptValidationError("invalid_snapshot_cursor")
    if (snapshot.turn_position == -1) != (snapshot.turn_id is None):
        raise RuntimeTranscriptValidationError("invalid_snapshot_cursor")
    if snapshot.event_position < -1 or snapshot.turn_position < -1:
        raise RuntimeTranscriptValidationError("invalid_snapshot_cursor")
    return snapshot


def _optional_identifier(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
