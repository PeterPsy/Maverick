"""Typed asset, caption, audio-envelope, template, and group operations."""

from __future__ import annotations

from typing import Any

from project_ir.canonical import canonical_copy

from .errors import ProjectError
from .operation_helpers import find_clip, require_fields, timeline


def apply_content_operation(document: dict[str, Any], operation: dict[str, Any]) -> bool:
    operation_type = operation["type"]
    handlers = {
        "asset.add": _add_asset,
        "asset.remove": _remove_asset,
        "caption.add": _add_caption,
        "caption.update": _update_caption,
        "caption.remove": _remove_caption,
        "audio.envelope.add": _add_envelope,
        "audio.envelope.update": _update_envelope,
        "audio.envelope.remove": _remove_envelope,
        "template.apply": _apply_template,
        "group.group": _group,
        "group.ungroup": _ungroup,
    }
    handler = handlers.get(operation_type)
    if handler is None:
        return False
    handler(document, operation)
    return True


def _add_asset(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"asset"}, "/operations")
    asset = operation["asset"]
    if not isinstance(asset, dict):
        raise ProjectError("asset_invalid", "Asset must be an object.")
    assets = document.setdefault("assets", [])
    if any(item.get("asset_id") == asset.get("asset_id") for item in assets):
        raise ProjectError("asset_exists", "Asset id already exists.", status_code=409)
    assets.append(canonical_copy(asset))
    assets.sort(key=lambda item: str(item.get("asset_id", "")))


def _remove_asset(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"asset_id"}, "/operations")
    asset_id = operation["asset_id"]
    for track in timeline(document).get("tracks", []):
        for clip in track.get("clips", []):
            if clip.get("asset_id") == asset_id:
                raise ProjectError("asset_in_use", "Asset is still referenced by a clip.", status_code=409)
            if any(layer.get("asset_id") == asset_id for layer in clip.get("layers", [])):
                raise ProjectError("asset_in_use", "Asset is still referenced by a layer.", status_code=409)
    assets = document.get("assets", [])
    target = next((item for item in assets if item.get("asset_id") == asset_id), None)
    if target is None:
        raise ProjectError("asset_not_found", "Asset was not found.", status_code=404)
    assets.remove(target)


def _add_caption(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"caption"}, "/operations")
    caption = operation["caption"]
    if not isinstance(caption, dict):
        raise ProjectError("caption_invalid", "Caption must be an object.")
    captions = timeline(document).setdefault("captions", [])
    if any(item.get("caption_id") == caption.get("caption_id") for item in captions):
        raise ProjectError("caption_exists", "Caption id already exists.", status_code=409)
    captions.append(canonical_copy(caption))
    _sort_captions(captions)


def _update_caption(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"caption_id", "changes"}, "/operations")
    changes = operation["changes"]
    allowed = {"track_id", "start_frame", "duration_frames", "text", "speaker", "style"}
    if not isinstance(changes, dict) or not changes or set(changes) - allowed:
        raise ProjectError("caption_changes_invalid", "Caption changes are outside the typed allowlist.")
    target = _find(timeline(document).get("captions", []), "caption_id", operation["caption_id"], "caption")
    target.update(canonical_copy(changes))
    _sort_captions(timeline(document)["captions"])


def _remove_caption(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"caption_id"}, "/operations")
    captions = timeline(document).get("captions", [])
    captions.remove(_find(captions, "caption_id", operation["caption_id"], "caption"))


def _add_envelope(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "point"}, "/operations")
    envelope = _envelope(document, operation["clip_id"])
    point = operation["point"]
    if not isinstance(point, dict):
        raise ProjectError("envelope_point_invalid", "Envelope point must be an object.")
    if any(item.get("frame") == point.get("frame") for item in envelope):
        raise ProjectError("envelope_point_exists", "Envelope frame already exists.", status_code=409)
    envelope.append(canonical_copy(point))
    envelope.sort(key=lambda item: item.get("frame", 0))


def _update_envelope(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "frame", "point"}, "/operations")
    envelope = _envelope(document, operation["clip_id"])
    target = next((item for item in envelope if item.get("frame") == operation["frame"]), None)
    if target is None:
        raise ProjectError("envelope_point_not_found", "Envelope point was not found.", status_code=404)
    point = operation["point"]
    if not isinstance(point, dict):
        raise ProjectError("envelope_point_invalid", "Envelope point must be an object.")
    target.clear()
    target.update(canonical_copy(point))
    envelope.sort(key=lambda item: item.get("frame", 0))


def _remove_envelope(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "frame"}, "/operations")
    envelope = _envelope(document, operation["clip_id"])
    target = next((item for item in envelope if item.get("frame") == operation["frame"]), None)
    if target is None:
        raise ProjectError("envelope_point_not_found", "Envelope point was not found.", status_code=404)
    envelope.remove(target)


def _apply_template(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"instance"}, "/operations")
    instance = operation["instance"]
    if not isinstance(instance, dict):
        raise ProjectError("template_instance_invalid", "Template instance must be an object.")
    instances = timeline(document).setdefault("template_instances", [])
    if any(item.get("template_instance_id") == instance.get("template_instance_id") for item in instances):
        raise ProjectError("template_instance_exists", "Template instance id already exists.", status_code=409)
    instances.append(canonical_copy(instance))
    instances.sort(key=lambda item: str(item.get("template_instance_id", "")))


def _group(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"group"}, "/operations")
    group = operation["group"]
    if not isinstance(group, dict):
        raise ProjectError("group_invalid", "Group must be an object.")
    groups = timeline(document).setdefault("groups", [])
    if any(item.get("group_id") == group.get("group_id") for item in groups):
        raise ProjectError("group_exists", "Group id already exists.", status_code=409)
    groups.append(canonical_copy(group))
    group_id = group.get("group_id")
    for member_id in group.get("member_ids", []):
        try:
            _, clip, _, _ = find_clip(document, member_id)
        except ProjectError:
            continue
        if group_id not in clip.setdefault("group_ids", []):
            clip["group_ids"].append(group_id)


def _ungroup(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"group_id"}, "/operations")
    groups = timeline(document).get("groups", [])
    group = _find(groups, "group_id", operation["group_id"], "group")
    groups.remove(group)
    for track in timeline(document).get("tracks", []):
        for clip in track.get("clips", []):
            clip["group_ids"] = [value for value in clip.get("group_ids", []) if value != operation["group_id"]]
    for parent in groups:
        parent["member_ids"] = [value for value in parent.get("member_ids", []) if value != operation["group_id"]]


def _envelope(document: dict[str, Any], clip_id: object) -> list[dict[str, Any]]:
    _, clip, _, _ = find_clip(document, clip_id)
    audio = clip.get("audio")
    if not isinstance(audio, dict) or not isinstance(audio.get("envelope"), list):
        raise ProjectError("audio_envelope_unavailable", "Clip has no editable audio envelope.")
    return audio["envelope"]


def _find(items: list[dict[str, Any]], field: str, identifier: object, kind: str) -> dict[str, Any]:
    target = next((item for item in items if item.get(field) == identifier), None)
    if target is None:
        raise ProjectError(f"{kind}_not_found", f"{kind.capitalize()} was not found.", status_code=404)
    return target


def _sort_captions(captions: list[dict[str, Any]]) -> None:
    captions.sort(key=lambda item: (item.get("start_frame", 0), str(item.get("caption_id", ""))))
