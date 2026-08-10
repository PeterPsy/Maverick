"""Typed insert, overwrite, move, trim, split, and ripple operations."""

from __future__ import annotations

from typing import Any

from .errors import ProjectError
from .operation_helpers import (
    clone_clip,
    derived_id,
    ensure_interval_available,
    find_clip,
    find_track,
    integer,
    require_fields,
    sorted_clips,
    source_boundary,
)


def apply_timeline_operation(
    document: dict[str, Any],
    operation: dict[str, Any],
    *,
    batch_id: str,
    operation_index: int,
) -> bool:
    operation_type = operation["type"]
    if operation_type == "timeline.insert":
        _insert(document, operation)
    elif operation_type == "timeline.overwrite":
        _overwrite(document, operation, batch_id, operation_index)
    elif operation_type == "timeline.move":
        _move(document, operation)
    elif operation_type == "timeline.trim":
        _trim(document, operation)
    elif operation_type == "timeline.split":
        _split(document, operation)
    elif operation_type == "timeline.ripple_delete":
        _ripple_delete(document, operation, batch_id, operation_index)
    elif operation_type == "timeline.ripple_trim":
        _ripple_trim(document, operation)
    else:
        return False
    return True


def _insert(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"track_id", "clip"}, "/operations")
    track, _ = find_track(document, operation["track_id"])
    clip = clone_clip(_clip_value(operation.get("clip")))
    start = integer(clip.get("start_frame"), "/clip/start_frame", minimum=0)
    duration = integer(clip.get("duration_frames"), "/clip/duration_frames", minimum=1)
    for current in track.get("clips", []):
        current_start = current.get("start_frame") if isinstance(current, dict) else None
        current_duration = current.get("duration_frames") if isinstance(current, dict) else None
        if isinstance(current_start, int) and isinstance(current_duration, int):
            if current_start < start < current_start + current_duration:
                raise ProjectError("insert_intersects_clip", "Insert point lies inside an existing clip.")
            if current_start >= start:
                current["start_frame"] = current_start + duration
    track.setdefault("clips", []).append(clip)
    sorted_clips(track)
    document["duration_frames"] = max(document.get("duration_frames", 0) + duration, start + duration)


def _overwrite(
    document: dict[str, Any],
    operation: dict[str, Any],
    batch_id: str,
    operation_index: int,
) -> None:
    require_fields(operation, {"track_id", "clip"}, "/operations")
    track, _ = find_track(document, operation["track_id"])
    inserted = clone_clip(_clip_value(operation.get("clip")))
    start = integer(inserted.get("start_frame"), "/clip/start_frame", minimum=0)
    duration = integer(inserted.get("duration_frames"), "/clip/duration_frames", minimum=1)
    end = start + duration
    remaining: list[dict[str, Any]] = []
    for current in track.get("clips", []):
        if not isinstance(current, dict):
            continue
        original = clone_clip(current)
        current_start = current.get("start_frame")
        current_duration = current.get("duration_frames")
        if not isinstance(current_start, int) or not isinstance(current_duration, int):
            remaining.append(current)
            continue
        current_end = current_start + current_duration
        if current_end <= start or current_start >= end:
            remaining.append(current)
            continue
        source_at_start = source_boundary(current, max(0, start - current_start))
        source_at_end = source_boundary(current, min(current_duration, end - current_start))
        if current_start < start:
            current["duration_frames"] = start - current_start
            if source_at_start is not None:
                current["source"]["out_pts"] = source_at_start
            remaining.append(current)
        if current_end > end:
            right = original
            right["clip_id"] = derived_id(str(current.get("clip_id")), batch_id, operation_index, "right")
            right["start_frame"] = end
            right["duration_frames"] = current_end - end
            if source_at_end is not None and isinstance(right.get("source"), dict):
                right["source"]["in_pts"] = source_at_end
            remaining.append(right)
    track["clips"] = remaining + [inserted]
    sorted_clips(track)
    document["duration_frames"] = max(document.get("duration_frames", 0), end)


def _move(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "target_track_id", "start_frame"}, "/operations")
    source_track, clip, _, source_index = find_clip(document, operation["clip_id"])
    target_track, _ = find_track(document, operation["target_track_id"])
    start = integer(operation["start_frame"], "/start_frame", minimum=0)
    duration = integer(clip.get("duration_frames"), "/duration_frames", minimum=1)
    ensure_interval_available(target_track, start, duration, excluding=str(clip.get("clip_id")))
    source_track["clips"].pop(source_index)
    clip["start_frame"] = start
    target_track.setdefault("clips", []).append(clip)
    sorted_clips(source_track)
    sorted_clips(target_track)
    document["duration_frames"] = max(document.get("duration_frames", 0), start + duration)


def _trim(document: dict[str, Any], operation: dict[str, Any]) -> None:
    fields = {"clip_id", "start_frame", "duration_frames", "source_in_pts", "source_out_pts"}
    require_fields(operation, fields, "/operations")
    track, clip, _, _ = find_clip(document, operation["clip_id"])
    start = integer(operation["start_frame"], "/start_frame", minimum=0)
    duration = integer(operation["duration_frames"], "/duration_frames", minimum=1)
    ensure_interval_available(track, start, duration, excluding=str(clip.get("clip_id")))
    clip["start_frame"] = start
    clip["duration_frames"] = duration
    if isinstance(clip.get("source"), dict):
        clip["source"] = {
            "in_pts": integer(operation["source_in_pts"], "/source_in_pts", minimum=0),
            "out_pts": integer(operation["source_out_pts"], "/source_out_pts", minimum=1),
        }
    sorted_clips(track)


def _split(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "frame", "right_clip_id"}, "/operations")
    track, clip, _, _ = find_clip(document, operation["clip_id"])
    frame = integer(operation["frame"], "/frame", minimum=0)
    start = integer(clip.get("start_frame"), "/clip/start_frame", minimum=0)
    duration = integer(clip.get("duration_frames"), "/clip/duration_frames", minimum=1)
    if not start < frame < start + duration:
        raise ProjectError("split_frame_invalid", "Split frame must lie strictly inside the clip.")
    boundary = source_boundary(clip, frame - start)
    right = clone_clip(clip)
    right["clip_id"] = operation["right_clip_id"]
    right["start_frame"] = frame
    right["duration_frames"] = start + duration - frame
    clip["duration_frames"] = frame - start
    if boundary is not None and isinstance(clip.get("source"), dict):
        clip["source"]["out_pts"] = boundary
        right["source"]["in_pts"] = boundary
    right["keyframes"] = []
    track["clips"].append(right)
    sorted_clips(track)


def _ripple_delete(
    document: dict[str, Any],
    operation: dict[str, Any],
    batch_id: str,
    operation_index: int,
) -> None:
    require_fields(operation, {"track_id", "start_frame", "duration_frames"}, "/operations")
    track, _ = find_track(document, operation["track_id"])
    start = integer(operation["start_frame"], "/start_frame", minimum=0)
    duration = integer(operation["duration_frames"], "/duration_frames", minimum=1)
    end = start + duration
    remaining: list[dict[str, Any]] = []
    for current in track.get("clips", []):
        if not isinstance(current, dict):
            continue
        original = clone_clip(current)
        current_start = current.get("start_frame", 0)
        current_duration = current.get("duration_frames", 0)
        current_end = current_start + current_duration
        if current_end <= start:
            remaining.append(current)
            continue
        if current_start >= end:
            current["start_frame"] = current_start - duration
            remaining.append(current)
            continue
        at_start = source_boundary(current, max(0, start - current_start))
        at_end = source_boundary(current, min(current_duration, end - current_start))
        if current_start < start:
            current["duration_frames"] = start - current_start
            if at_start is not None and isinstance(current.get("source"), dict):
                current["source"]["out_pts"] = at_start
            remaining.append(current)
        if current_end > end:
            right = original
            right["clip_id"] = derived_id(str(current.get("clip_id")), batch_id, operation_index, "ripple")
            right["start_frame"] = start
            right["duration_frames"] = current_end - end
            if at_end is not None and isinstance(right.get("source"), dict):
                right["source"]["in_pts"] = at_end
            remaining.append(right)
    track["clips"] = remaining
    sorted_clips(track)
    document["duration_frames"] = max(
        _latest_content_end(document),
        max(0, document.get("duration_frames", 0) - duration),
    )


def _ripple_trim(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "edge", "delta_frames"}, "/operations")
    track, clip, _, _ = find_clip(document, operation["clip_id"])
    delta = integer(operation["delta_frames"], "/delta_frames")
    edge = operation["edge"]
    start = integer(clip.get("start_frame"), "/clip/start_frame", minimum=0)
    duration = integer(clip.get("duration_frames"), "/clip/duration_frames", minimum=1)
    if edge == "end":
        new_duration = duration + delta
        if new_duration <= 0:
            raise ProjectError("ripple_trim_invalid", "Ripple trim would remove the complete clip.")
        boundary = source_boundary(clip, new_duration)
        old_end = start + duration
        clip["duration_frames"] = new_duration
        if boundary is not None and isinstance(clip.get("source"), dict):
            clip["source"]["out_pts"] = boundary
        for current in track.get("clips", []):
            if current is not clip and current.get("start_frame", -1) >= old_end:
                current["start_frame"] += delta
        document["duration_frames"] = max(
            _latest_content_end(document),
            max(0, document.get("duration_frames", 0) + delta),
        )
    elif edge == "start":
        if not 0 <= delta < duration:
            raise ProjectError("ripple_trim_invalid", "Start ripple trim delta is outside the clip.")
        boundary = source_boundary(clip, delta)
        clip["start_frame"] = start + delta
        clip["duration_frames"] = duration - delta
        if boundary is not None and isinstance(clip.get("source"), dict):
            clip["source"]["in_pts"] = boundary
    else:
        raise ProjectError("ripple_trim_edge_invalid", "Ripple trim edge must be start or end.")
    sorted_clips(track)


def _clip_value(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectError("clip_invalid", "Operation clip must be an object.", path="/clip")
    return value


def _latest_content_end(document: dict[str, Any]) -> int:
    ends = [0]
    timeline = document.get("timeline", {})
    for track in timeline.get("tracks", []):
        for clip in track.get("clips", []):
            start, duration = clip.get("start_frame"), clip.get("duration_frames")
            if isinstance(start, int) and isinstance(duration, int):
                ends.append(start + duration)
    for collection in ("captions", "template_instances"):
        for item in timeline.get(collection, []):
            start, duration = item.get("start_frame"), item.get("duration_frames")
            if isinstance(start, int) and isinstance(duration, int):
                ends.append(start + duration)
    return max(ends)
