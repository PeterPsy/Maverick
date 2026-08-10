"""Clip, layer, keyframe, effect, and audio invariants."""

from __future__ import annotations

from typing import Any

from .errors import ValidationIssue, issue
from .invariants import IRIndex
from .registry import ProjectRegistry


TRACK_CLIP_COMPATIBILITY = {
    "video": {"video", "image", "compound"},
    "audio": {"audio"},
    "text": {"text"},
    "captions": {"caption"},
    "graphics": {"image", "text", "shape", "template", "compound"},
}
ASSET_CLIP_KINDS = {"video", "audio", "image"}


def clip_invariant_issues(
    document: dict[str, Any],
    index: IRIndex,
    registry: ProjectRegistry,
) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    duration = document.get("duration_frames")
    project_duration = duration if _integer(duration) and duration >= 0 else 0
    timeline = _dict(document.get("timeline"))
    for track_pos, track in enumerate(_list(timeline.get("tracks"))):
        if not isinstance(track, dict):
            continue
        track_type = track.get("type")
        track_path = f"/timeline/tracks/{track_pos}"
        if track_type not in TRACK_CLIP_COMPATIBILITY:
            problems.append(issue("track_type_invalid", f"{track_path}/type", "Track type is unsupported."))
        for clip_pos, clip in enumerate(_list(track.get("clips"))):
            if isinstance(clip, dict):
                problems.extend(
                    _clip_issues(
                        clip,
                        f"{track_path}/clips/{clip_pos}",
                        track_type,
                        project_duration,
                        index,
                        registry,
                    )
                )
    return problems


def _clip_issues(
    clip: dict[str, Any],
    path: str,
    track_type: object,
    project_duration: int,
    index: IRIndex,
    registry: ProjectRegistry,
) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    clip_kind = clip.get("kind")
    allowed = TRACK_CLIP_COMPATIBILITY.get(str(track_type), set())
    if clip_kind not in allowed:
        problems.append(issue("track_clip_incompatible", f"{path}/kind", "Clip kind is incompatible with its track type."))
    start = clip.get("start_frame")
    duration = clip.get("duration_frames")
    if not _integer(start) or start < 0:
        problems.append(issue("clip_start_invalid", f"{path}/start_frame", "Clip start must be a non-negative integer frame."))
        start = 0
    if not _integer(duration) or duration <= 0:
        problems.append(issue("clip_duration_invalid", f"{path}/duration_frames", "Clip duration must be a positive integer frame count."))
        duration = 0
    if start + duration > project_duration:
        problems.append(issue("clip_outside_project", path, "Clip interval exceeds project duration."))
    asset_id = clip.get("asset_id")
    if clip_kind in ASSET_CLIP_KINDS:
        asset = index.assets.get(asset_id) if isinstance(asset_id, str) else None
        if asset is None:
            problems.append(issue("asset_reference_missing", f"{path}/asset_id", "Clip references a missing asset."))
        elif asset.get("kind") != clip_kind:
            problems.append(issue("asset_clip_incompatible", f"{path}/asset_id", "Asset kind is incompatible with clip kind."))
        problems.extend(_source_range_issues(clip, asset, path))
    elif asset_id is not None:
        problems.append(issue("asset_reference_unexpected", f"{path}/asset_id", "This clip kind must not reference a source asset."))
    problems.extend(_visual_issues(clip, path, registry))
    problems.extend(_keyframe_issues(clip, path, duration, registry))
    problems.extend(_effect_issues(clip, path, registry))
    problems.extend(_audio_issues(clip, path, duration, track_type))
    problems.extend(_text_issues(clip, path, registry))
    for layer_pos, layer in enumerate(_list(clip.get("layers"))):
        if isinstance(layer, dict):
            problems.extend(_layer_issues(layer, f"{path}/layers/{layer_pos}", index, registry))
    for group_pos, group_id in enumerate(_list(clip.get("group_ids"))):
        if not isinstance(group_id, str) or group_id not in index.groups:
            problems.append(issue("group_reference_missing", f"{path}/group_ids/{group_pos}", "Clip references a missing group."))
    return problems


def _source_range_issues(
    clip: dict[str, Any],
    asset: dict[str, Any] | None,
    path: str,
) -> list[ValidationIssue]:
    source = clip.get("source")
    if not isinstance(source, dict) or set(source) != {"in_pts", "out_pts"}:
        return [issue("source_range_invalid", f"{path}/source", "Source range requires integer in_pts and out_pts.")]
    source_in = source.get("in_pts")
    source_out = source.get("out_pts")
    if not _integer(source_in) or not _integer(source_out) or source_in < 0 or source_out <= source_in:
        return [issue("source_range_invalid", f"{path}/source", "Source range must be non-negative and increasing.")]
    asset_duration = _dict(_dict(asset).get("source")).get("duration_pts")
    if _integer(asset_duration) and source_out > asset_duration:
        return [issue("source_range_exceeds_asset", f"{path}/source/out_pts", "Source range exceeds asset duration.")]
    return []


def _visual_issues(value: dict[str, Any], path: str, registry: ProjectRegistry) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    opacity = value.get("opacity_permille", 1000)
    if not _integer(opacity) or not 0 <= opacity <= 1000:
        problems.append(issue("opacity_invalid", f"{path}/opacity_permille", "Opacity must be an integer from 0 through 1000."))
    if value.get("fit", "contain") not in registry.fit_modes:
        problems.append(issue("fit_not_allowed", f"{path}/fit", "Fit mode is not allowlisted."))
    if value.get("compositing", "source-over") not in registry.compositing_modes:
        problems.append(issue("compositing_not_allowed", f"{path}/compositing", "Compositing mode is not allowlisted."))
    transform = value.get("transform", {})
    expected_transform = {"x_millipixels", "y_millipixels", "scale_x_permille", "scale_y_permille", "rotation_millidegrees", "anchor_x_permille", "anchor_y_permille"}
    if not isinstance(transform, dict) or set(transform) - expected_transform or any(not _integer(item) for item in transform.values()):
        problems.append(issue("transform_invalid", f"{path}/transform", "Transform must use declared integer fixed-point fields."))
    crop = value.get("crop", {})
    expected_crop = {"left_pixels", "top_pixels", "right_pixels", "bottom_pixels"}
    if not isinstance(crop, dict) or set(crop) - expected_crop or any(not _integer(item) or item < 0 for item in crop.values()):
        problems.append(issue("crop_invalid", f"{path}/crop", "Crop must use non-negative integer pixel fields."))
    return problems


def _keyframe_issues(clip: dict[str, Any], path: str, duration: int, registry: ProjectRegistry) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    previous_by_property: dict[str, int] = {}
    for position, keyframe in enumerate(_list(clip.get("keyframes"))):
        key_path = f"{path}/keyframes/{position}"
        if not isinstance(keyframe, dict) or set(keyframe) != {"keyframe_id", "property", "frame", "value", "easing"}:
            problems.append(issue("keyframe_shape_invalid", key_path, "Keyframe fields do not match Project IR v1."))
            continue
        frame = keyframe.get("frame")
        prop = keyframe.get("property")
        if not _integer(frame) or frame < 0 or frame > duration:
            problems.append(issue("keyframe_outside_clip", f"{key_path}/frame", "Keyframe must lie inside the clip."))
        if not isinstance(prop, str) or not prop:
            problems.append(issue("keyframe_property_invalid", f"{key_path}/property", "Keyframe property is required."))
        elif _integer(frame):
            previous = previous_by_property.get(prop, -1)
            if frame <= previous:
                problems.append(issue("keyframes_not_ordered", f"{key_path}/frame", "Keyframes for a property must be strictly ordered."))
            previous_by_property[prop] = frame
        if keyframe.get("easing") not in registry.easings:
            problems.append(issue("easing_not_allowed", f"{key_path}/easing", "Keyframe easing is not allowlisted."))
        if isinstance(keyframe.get("value"), float):
            problems.append(issue("keyframe_value_float", f"{key_path}/value", "Keyframe authority must not use floating point."))
    return problems


def _effect_issues(clip: dict[str, Any], path: str, registry: ProjectRegistry) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    for position, effect in enumerate(_list(clip.get("effects"))):
        effect_path = f"{path}/effects/{position}"
        if not isinstance(effect, dict) or set(effect) != {"effect_id", "registry", "enabled", "parameters"}:
            problems.append(issue("effect_shape_invalid", effect_path, "Effect fields do not match Project IR v1."))
            continue
        if not isinstance(effect.get("enabled"), bool):
            problems.append(issue("effect_enabled_invalid", f"{effect_path}/enabled", "Effect enabled state must be boolean."))
        problems.extend(registry.validate_effect(effect.get("registry"), effect.get("parameters"), effect_path))
    return problems


def _audio_issues(clip: dict[str, Any], path: str, duration: int, track_type: object) -> list[ValidationIssue]:
    audio = clip.get("audio")
    if audio is None:
        return []
    if track_type != "audio" or not isinstance(audio, dict):
        return [issue("audio_settings_incompatible", f"{path}/audio", "Audio settings require an audio track clip.")]
    problems: list[ValidationIssue] = []
    allowed = {"gain_millibels", "pan_milli", "mute", "channel_mapping", "fade_in_frames", "fade_out_frames", "envelope"}
    if set(audio) != allowed:
        problems.append(issue("audio_shape_invalid", f"{path}/audio", "Audio settings fields do not match Project IR v1."))
    for name, minimum, maximum in (("gain_millibels", -9600, 2400), ("pan_milli", -1000, 1000)):
        value = audio.get(name)
        if not _integer(value) or not minimum <= value <= maximum:
            problems.append(issue("audio_value_invalid", f"{path}/audio/{name}", "Audio value is outside its fixed-point range."))
    if not isinstance(audio.get("mute"), bool):
        problems.append(issue("audio_mute_invalid", f"{path}/audio/mute", "Audio mute must be boolean."))
    for name in ("fade_in_frames", "fade_out_frames"):
        value = audio.get(name)
        if not _integer(value) or value < 0 or value > duration:
            problems.append(issue("audio_fade_invalid", f"{path}/audio/{name}", "Audio fade must lie inside the clip."))
    envelope = _list(audio.get("envelope"))
    frames = [item.get("frame") for item in envelope if isinstance(item, dict)]
    if any(not _integer(frame) or frame < 0 or frame > duration for frame in frames) or frames != sorted(set(frames)):
        problems.append(issue("audio_envelope_invalid", f"{path}/audio/envelope", "Audio envelope frames must be unique, ordered, and inside the clip."))
    return problems


def _text_issues(clip: dict[str, Any], path: str, registry: ProjectRegistry) -> list[ValidationIssue]:
    text = clip.get("text")
    if text is None:
        return []
    if clip.get("kind") not in {"text", "caption", "template"} or not isinstance(text, dict):
        return [issue("text_incompatible", f"{path}/text", "Text content is incompatible with this clip.")]
    problems: list[ValidationIssue] = []
    if set(text) != {"plain_text", "font", "size_millipixels", "color", "align", "runs"}:
        problems.append(issue("text_shape_invalid", f"{path}/text", "Text fields do not match the safe text profile."))
    if not isinstance(text.get("plain_text"), str):
        problems.append(issue("text_value_invalid", f"{path}/text/plain_text", "Text content must be plain text."))
    font = text.get("font")
    if not isinstance(font, dict) or (font.get("id"), font.get("version")) not in registry.fonts:
        problems.append(issue("font_not_registered", f"{path}/text/font", "Text font is not registered."))
    return problems


def _layer_issues(layer: dict[str, Any], path: str, index: IRIndex, registry: ProjectRegistry) -> list[ValidationIssue]:
    problems = _visual_issues(layer, path, registry)
    asset_id = layer.get("asset_id")
    if asset_id is not None and asset_id not in index.assets:
        problems.append(issue("asset_reference_missing", f"{path}/asset_id", "Layer references a missing asset."))
    problems.extend(_effect_issues({"effects": layer.get("effects", [])}, path, registry))
    return problems


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
