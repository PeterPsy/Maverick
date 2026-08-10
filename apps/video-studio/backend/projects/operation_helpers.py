"""Shared bounded lookup and deterministic timeline helpers."""

from __future__ import annotations

import hashlib
from typing import Any

from project_ir.canonical import canonical_copy

from .errors import ProjectError


def timeline(document: dict[str, Any]) -> dict[str, Any]:
    value = document.get("timeline")
    if not isinstance(value, dict):
        raise ProjectError("timeline_missing", "Project timeline is unavailable.")
    return value


def find_track(document: dict[str, Any], track_id: object) -> tuple[dict[str, Any], int]:
    for index, track in enumerate(timeline(document).get("tracks", [])):
        if isinstance(track, dict) and track.get("track_id") == track_id:
            return track, index
    raise ProjectError(
        "track_not_found",
        "Timeline track was not found.",
        path="/track_id",
        details={"track_id": track_id},
        status_code=404,
    )


def find_clip(
    document: dict[str, Any],
    clip_id: object,
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    for track_index, track in enumerate(timeline(document).get("tracks", [])):
        if not isinstance(track, dict):
            continue
        for clip_index, clip in enumerate(track.get("clips", [])):
            if isinstance(clip, dict) and clip.get("clip_id") == clip_id:
                return track, clip, track_index, clip_index
    raise ProjectError(
        "clip_not_found",
        "Timeline clip was not found.",
        path="/clip_id",
        details={"clip_id": clip_id},
        status_code=404,
    )


def require_fields(operation: dict[str, Any], fields: set[str], path: str) -> None:
    expected = fields | {"type"}
    missing = sorted(expected - set(operation))
    unknown = sorted(set(operation) - expected)
    if missing or unknown:
        raise ProjectError(
            "operation_shape_invalid",
            "Operation fields do not match its typed contract.",
            path=path,
            details={"missing": missing, "unknown": unknown},
        )


def integer(value: object, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or (minimum is not None and value < minimum):
        raise ProjectError("integer_invalid", "Operation value must be an integer in range.", path=path)
    return value


def derived_id(original_id: str, batch_id: str, operation_index: int, suffix: str) -> str:
    digest = hashlib.sha256(
        f"{batch_id}:{operation_index}:{original_id}:{suffix}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{original_id}.{suffix}.{digest}"[:128]


def sorted_clips(track: dict[str, Any]) -> None:
    track["clips"] = sorted(
        track.get("clips", []),
        key=lambda clip: (clip.get("start_frame", 0), str(clip.get("clip_id", ""))),
    )


def ensure_interval_available(
    track: dict[str, Any],
    start: int,
    duration: int,
    *,
    excluding: str | None = None,
) -> None:
    end = start + duration
    for clip in track.get("clips", []):
        if not isinstance(clip, dict) or clip.get("clip_id") == excluding:
            continue
        clip_start = clip.get("start_frame")
        clip_duration = clip.get("duration_frames")
        if isinstance(clip_start, int) and isinstance(clip_duration, int):
            if start < clip_start + clip_duration and clip_start < end:
                raise ProjectError(
                    "timeline_collision",
                    "Operation would create overlapping clips on one track.",
                    details={"conflicting_clip_id": clip.get("clip_id")},
                    status_code=409,
                )


def clone_clip(clip: dict[str, Any]) -> dict[str, Any]:
    return canonical_copy(clip)


def source_boundary(clip: dict[str, Any], relative_frame: int) -> int | None:
    source = clip.get("source")
    duration = clip.get("duration_frames")
    if not isinstance(source, dict) or not isinstance(duration, int) or duration <= 0:
        return None
    source_in = source.get("in_pts")
    source_out = source.get("out_pts")
    if not isinstance(source_in, int) or not isinstance(source_out, int):
        return None
    numerator = (source_out - source_in) * relative_frame
    quotient, remainder = divmod(numerator, duration)
    if remainder * 2 > duration or (remainder * 2 == duration and quotient % 2):
        quotient += 1
    return source_in + quotient
