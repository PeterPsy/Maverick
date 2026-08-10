"""Strict structural profile for Project IR v1."""

from __future__ import annotations

from typing import Any

from .errors import ValidationIssue, issue


ROOT_FIELDS = {
    "ir_version",
    "metadata",
    "canvas",
    "frame_rate",
    "audio",
    "duration_frames",
    "assets",
    "timeline",
}
TIMELINE_FIELDS = {
    "tracks",
    "transitions",
    "captions",
    "markers",
    "template_instances",
    "groups",
    "relationships",
}
TRACK_FIELDS = {"track_id", "type", "name", "enabled", "locked", "muted", "clips"}
CLIP_FIELDS = {
    "clip_id",
    "kind",
    "asset_id",
    "start_frame",
    "duration_frames",
    "source",
    "transform",
    "crop",
    "fit",
    "opacity_permille",
    "compositing",
    "audio",
    "keyframes",
    "effects",
    "layers",
    "text",
    "template_instance_id",
    "caption_id",
    "group_ids",
}
ASSET_FIELDS = {"asset_id", "kind", "identity", "provenance", "source"}
LAYER_FIELDS = {
    "layer_id",
    "kind",
    "asset_id",
    "transform",
    "crop",
    "fit",
    "opacity_permille",
    "compositing",
    "effects",
    "text",
}


def structural_issues(document: object) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    if not isinstance(document, dict):
        return [issue("document_type", "", "Project IR must be a JSON object.")]
    _fields(document, ROOT_FIELDS, ROOT_FIELDS, "", problems)
    _string(document.get("ir_version"), "/ir_version", problems)
    _object(document.get("metadata"), "/metadata", problems)
    _object(document.get("canvas"), "/canvas", problems)
    _rational(document.get("frame_rate"), "/frame_rate", problems)
    _object(document.get("audio"), "/audio", problems)
    _integer(document.get("duration_frames"), "/duration_frames", problems)
    assets = _array(document.get("assets"), "/assets", problems)
    timeline = _object(document.get("timeline"), "/timeline", problems)

    if isinstance(document.get("metadata"), dict):
        metadata = document["metadata"]
        _fields(metadata, {"project_id", "workspace_id", "name", "tags", "provenance"},
                {"project_id", "workspace_id", "name", "tags", "provenance"}, "/metadata", problems)
        for name in ("project_id", "workspace_id", "name"):
            _string(metadata.get(name), f"/metadata/{name}", problems)
        _array(metadata.get("tags"), "/metadata/tags", problems)
        _array(metadata.get("provenance"), "/metadata/provenance", problems)

    if isinstance(document.get("canvas"), dict):
        canvas = document["canvas"]
        _fields(canvas, {"width", "height", "pixel_aspect", "background", "color_space"},
                {"width", "height", "pixel_aspect", "background", "color_space"}, "/canvas", problems)
        _integer(canvas.get("width"), "/canvas/width", problems)
        _integer(canvas.get("height"), "/canvas/height", problems)
        _rational(canvas.get("pixel_aspect"), "/canvas/pixel_aspect", problems)
        _object(canvas.get("background"), "/canvas/background", problems)
        _string(canvas.get("color_space"), "/canvas/color_space", problems)

    if isinstance(document.get("audio"), dict):
        audio = document["audio"]
        _fields(audio, {"sample_rate", "channel_layout"}, {"sample_rate", "channel_layout"}, "/audio", problems)
        _integer(audio.get("sample_rate"), "/audio/sample_rate", problems)
        _string(audio.get("channel_layout"), "/audio/channel_layout", problems)

    for index, asset in enumerate(assets):
        path = f"/assets/{index}"
        if not isinstance(asset, dict):
            problems.append(issue("object_type", path, "Asset must be an object."))
            continue
        _fields(asset, ASSET_FIELDS, ASSET_FIELDS, path, problems)
        _string(asset.get("asset_id"), f"{path}/asset_id", problems)
        _string(asset.get("kind"), f"{path}/kind", problems)
        _object(asset.get("identity"), f"{path}/identity", problems)
        _object(asset.get("provenance"), f"{path}/provenance", problems)
        _object(asset.get("source"), f"{path}/source", problems)

    if timeline:
        _fields(timeline, TIMELINE_FIELDS, TIMELINE_FIELDS, "/timeline", problems)
        for name in sorted(TIMELINE_FIELDS):
            _array(timeline.get(name), f"/timeline/{name}", problems)
        for track_index, track in enumerate(_items(timeline.get("tracks"))):
            _track(track, track_index, problems)
    return problems


def _track(track: Any, index: int, problems: list[ValidationIssue]) -> None:
    path = f"/timeline/tracks/{index}"
    if not isinstance(track, dict):
        problems.append(issue("object_type", path, "Track must be an object."))
        return
    _fields(track, TRACK_FIELDS, TRACK_FIELDS, path, problems)
    for name in ("track_id", "type", "name"):
        _string(track.get(name), f"{path}/{name}", problems)
    for name in ("enabled", "locked", "muted"):
        if not isinstance(track.get(name), bool):
            problems.append(issue("boolean_type", f"{path}/{name}", "Field must be a boolean."))
    clips = _array(track.get("clips"), f"{path}/clips", problems)
    for clip_index, clip in enumerate(clips):
        _clip(clip, f"{path}/clips/{clip_index}", problems)


def _clip(clip: Any, path: str, problems: list[ValidationIssue]) -> None:
    if not isinstance(clip, dict):
        problems.append(issue("object_type", path, "Clip must be an object."))
        return
    required = {"clip_id", "kind", "start_frame", "duration_frames", "keyframes", "effects", "layers", "group_ids"}
    _fields(clip, CLIP_FIELDS, required, path, problems)
    _string(clip.get("clip_id"), f"{path}/clip_id", problems)
    _string(clip.get("kind"), f"{path}/kind", problems)
    _integer(clip.get("start_frame"), f"{path}/start_frame", problems)
    _integer(clip.get("duration_frames"), f"{path}/duration_frames", problems)
    for name in ("keyframes", "effects", "layers", "group_ids"):
        _array(clip.get(name), f"{path}/{name}", problems)
    for layer_index, layer in enumerate(_items(clip.get("layers"))):
        layer_path = f"{path}/layers/{layer_index}"
        if not isinstance(layer, dict):
            problems.append(issue("object_type", layer_path, "Layer must be an object."))
        else:
            _fields(layer, LAYER_FIELDS, {"layer_id", "kind", "effects"}, layer_path, problems)


def _fields(
    value: dict[str, Any],
    allowed: set[str],
    required: set[str],
    path: str,
    problems: list[ValidationIssue],
) -> None:
    for name in sorted(required - set(value)):
        problems.append(issue("required_field", f"{path}/{name}", "Required field is missing."))
    for name in sorted(set(value) - allowed):
        problems.append(issue("unknown_field", f"{path}/{name}", "Field is not declared by Project IR v1."))


def _object(value: Any, path: str, problems: list[ValidationIssue]) -> dict[str, Any]:
    if not isinstance(value, dict):
        problems.append(issue("object_type", path, "Field must be an object."))
        return {}
    return value


def _array(value: Any, path: str, problems: list[ValidationIssue]) -> list[Any]:
    if not isinstance(value, list):
        problems.append(issue("array_type", path, "Field must be an array."))
        return []
    return value


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string(value: Any, path: str, problems: list[ValidationIssue]) -> None:
    if not isinstance(value, str) or not value.strip():
        problems.append(issue("string_type", path, "Field must be a non-empty string."))


def _integer(value: Any, path: str, problems: list[ValidationIssue]) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(issue("integer_type", path, "Field must be an integer."))


def _rational(value: Any, path: str, problems: list[ValidationIssue]) -> None:
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        problems.append(issue("rational_shape", path, "Rational must contain only numerator and denominator."))
        return
    _integer(value.get("numerator"), f"{path}/numerator", problems)
    _integer(value.get("denominator"), f"{path}/denominator", problems)
