"""Typed property, transition, effect, and keyframe operations."""

from __future__ import annotations

from typing import Any

from project_ir.canonical import canonical_copy

from .errors import ProjectError
from .operation_helpers import find_clip, find_track, require_fields, timeline


CLIP_PROPERTIES = {
    "start_frame",
    "duration_frames",
    "fit",
    "opacity_permille",
    "compositing",
    "transform.x_millipixels",
    "transform.y_millipixels",
    "transform.scale_x_permille",
    "transform.scale_y_permille",
    "transform.rotation_millidegrees",
    "transform.anchor_x_permille",
    "transform.anchor_y_permille",
    "crop.left_pixels",
    "crop.top_pixels",
    "crop.right_pixels",
    "crop.bottom_pixels",
    "audio.gain_millibels",
    "audio.pan_milli",
    "audio.mute",
}
TRACK_PROPERTIES = {"name", "enabled", "locked", "muted"}


def apply_property_operation(document: dict[str, Any], operation: dict[str, Any]) -> bool:
    operation_type = operation["type"]
    if operation_type == "property.set":
        _set_property(document, operation)
    elif operation_type == "project.rename":
        _rename(document, operation)
    elif operation_type == "transition.add":
        _add_transition(document, operation)
    elif operation_type == "transition.remove":
        _remove_transition(document, operation)
    elif operation_type == "effect.add":
        _add_effect(document, operation)
    elif operation_type == "effect.remove":
        _remove_effect(document, operation)
    elif operation_type == "keyframe.add":
        _add_keyframe(document, operation)
    elif operation_type == "keyframe.update":
        _update_keyframe(document, operation)
    elif operation_type == "keyframe.remove":
        _remove_keyframe(document, operation)
    else:
        return False
    return True


def _set_property(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"target_type", "target_id", "property", "value"}, "/operations")
    target_type = operation["target_type"]
    property_name = operation["property"]
    if target_type == "clip":
        _, target, _, _ = find_clip(document, operation["target_id"])
        allowed = CLIP_PROPERTIES
    elif target_type == "track":
        target, _ = find_track(document, operation["target_id"])
        allowed = TRACK_PROPERTIES
    elif target_type == "project":
        if operation["target_id"] != document.get("metadata", {}).get("project_id"):
            raise ProjectError("project_not_found", "Property target project is invalid.")
        target = document
        allowed = {"duration_frames"}
    else:
        raise ProjectError("property_target_invalid", "Property target type is unsupported.")
    if property_name not in allowed:
        raise ProjectError(
            "property_not_editable",
            "Property is outside the typed editing allowlist.",
            path="/property",
            details={"property": property_name, "target_type": target_type},
        )
    parts = property_name.split(".")
    current = target
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ProjectError("property_container_invalid", "Property container is not an object.")
        current = child
    current[parts[-1]] = canonical_copy(operation["value"])


def _rename(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"name"}, "/operations")
    name = operation["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 256:
        raise ProjectError("project_name_invalid", "Project name must be between 1 and 256 characters.")
    document["metadata"]["name"] = name.strip()


def _add_transition(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"transition"}, "/operations")
    value = operation["transition"]
    if not isinstance(value, dict):
        raise ProjectError("transition_invalid", "Transition must be an object.")
    transitions = timeline(document).setdefault("transitions", [])
    if any(item.get("transition_id") == value.get("transition_id") for item in transitions):
        raise ProjectError("transition_exists", "Transition id already exists.", status_code=409)
    transitions.append(canonical_copy(value))
    transitions.sort(key=lambda item: str(item.get("transition_id", "")))


def _remove_transition(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"transition_id"}, "/operations")
    _remove_by_id(timeline(document).get("transitions", []), "transition_id", operation["transition_id"], "transition")


def _add_effect(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "effect"}, "/operations")
    _, clip, _, _ = find_clip(document, operation["clip_id"])
    value = operation["effect"]
    if not isinstance(value, dict):
        raise ProjectError("effect_invalid", "Effect must be an object.")
    effects = clip.setdefault("effects", [])
    if any(item.get("effect_id") == value.get("effect_id") for item in effects):
        raise ProjectError("effect_exists", "Effect id already exists.", status_code=409)
    effects.append(canonical_copy(value))


def _remove_effect(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "effect_id"}, "/operations")
    _, clip, _, _ = find_clip(document, operation["clip_id"])
    _remove_by_id(clip.get("effects", []), "effect_id", operation["effect_id"], "effect")


def _add_keyframe(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "keyframe"}, "/operations")
    _, clip, _, _ = find_clip(document, operation["clip_id"])
    value = operation["keyframe"]
    if not isinstance(value, dict):
        raise ProjectError("keyframe_invalid", "Keyframe must be an object.")
    keyframes = clip.setdefault("keyframes", [])
    if any(item.get("keyframe_id") == value.get("keyframe_id") for item in keyframes):
        raise ProjectError("keyframe_exists", "Keyframe id already exists.", status_code=409)
    keyframes.append(canonical_copy(value))
    _sort_keyframes(keyframes)


def _update_keyframe(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "keyframe_id", "changes"}, "/operations")
    _, clip, _, _ = find_clip(document, operation["clip_id"])
    changes = operation["changes"]
    if not isinstance(changes, dict) or not changes or set(changes) - {"property", "frame", "value", "easing"}:
        raise ProjectError("keyframe_changes_invalid", "Keyframe changes are outside the typed allowlist.")
    target = _find_by_id(clip.get("keyframes", []), "keyframe_id", operation["keyframe_id"], "keyframe")
    target.update(canonical_copy(changes))
    _sort_keyframes(clip["keyframes"])


def _remove_keyframe(document: dict[str, Any], operation: dict[str, Any]) -> None:
    require_fields(operation, {"clip_id", "keyframe_id"}, "/operations")
    _, clip, _, _ = find_clip(document, operation["clip_id"])
    _remove_by_id(clip.get("keyframes", []), "keyframe_id", operation["keyframe_id"], "keyframe")


def _sort_keyframes(keyframes: list[dict[str, Any]]) -> None:
    keyframes.sort(key=lambda item: (str(item.get("property", "")), item.get("frame", 0), str(item.get("keyframe_id", ""))))


def _find_by_id(items: list[dict[str, Any]], field: str, identifier: object, kind: str) -> dict[str, Any]:
    for item in items:
        if item.get(field) == identifier:
            return item
    raise ProjectError(f"{kind}_not_found", f"{kind.capitalize()} was not found.", status_code=404)


def _remove_by_id(items: list[dict[str, Any]], field: str, identifier: object, kind: str) -> None:
    target = _find_by_id(items, field, identifier, kind)
    items.remove(target)
