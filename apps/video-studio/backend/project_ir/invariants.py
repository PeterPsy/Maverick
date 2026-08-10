"""Cross-document identity, reference, and timeline invariants."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import gcd
import re
from typing import Any

from .errors import ValidationIssue, issue
from .registry import ProjectRegistry
from .temporal import Rational, pts_to_microseconds


IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ASSET_KINDS = {"video", "audio", "image", "font", "template"}
CHANNEL_LAYOUTS = {"mono", "stereo", "5.1", "7.1"}


@dataclass
class IRIndex:
    id_paths: dict[str, str] = field(default_factory=dict)
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    clips: dict[str, dict[str, Any]] = field(default_factory=dict)
    clip_tracks: dict[str, tuple[str, str]] = field(default_factory=dict)
    tracks: dict[str, str] = field(default_factory=dict)
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    captions: dict[str, dict[str, Any]] = field(default_factory=dict)
    template_instances: dict[str, dict[str, Any]] = field(default_factory=dict)


def build_index(document: dict[str, Any], problems: list[ValidationIssue]) -> IRIndex:
    index = IRIndex()

    def register(identifier: object, path: str) -> str | None:
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            problems.append(issue("id_invalid", path, "Identifier is missing or malformed."))
            return None
        previous = index.id_paths.get(identifier)
        if previous is not None:
            problems.append(
                issue("id_duplicate", path, "Identifier must be globally unique.", first_path=previous)
            )
            return None
        index.id_paths[identifier] = path
        return identifier

    for asset_pos, asset in enumerate(_list(document.get("assets"))):
        if not isinstance(asset, dict):
            continue
        path = f"/assets/{asset_pos}/asset_id"
        identifier = register(asset.get("asset_id"), path)
        if identifier:
            index.assets[identifier] = asset
    timeline = _dict(document.get("timeline"))
    for track_pos, track in enumerate(_list(timeline.get("tracks"))):
        if not isinstance(track, dict):
            continue
        track_id = register(track.get("track_id"), f"/timeline/tracks/{track_pos}/track_id")
        track_type = str(track.get("type") or "")
        if track_id:
            index.tracks[track_id] = track_type
        for clip_pos, clip in enumerate(_list(track.get("clips"))):
            if not isinstance(clip, dict):
                continue
            base = f"/timeline/tracks/{track_pos}/clips/{clip_pos}"
            clip_id = register(clip.get("clip_id"), f"{base}/clip_id")
            if clip_id:
                index.clips[clip_id] = clip
                index.clip_tracks[clip_id] = (track_id or "", track_type)
            for layer_pos, layer in enumerate(_list(clip.get("layers"))):
                if isinstance(layer, dict):
                    register(layer.get("layer_id"), f"{base}/layers/{layer_pos}/layer_id")
            for effect_pos, effect in enumerate(_list(clip.get("effects"))):
                if isinstance(effect, dict):
                    register(effect.get("effect_id"), f"{base}/effects/{effect_pos}/effect_id")
            for key_pos, keyframe in enumerate(_list(clip.get("keyframes"))):
                if isinstance(keyframe, dict):
                    register(keyframe.get("keyframe_id"), f"{base}/keyframes/{key_pos}/keyframe_id")
    collections = (
        ("transitions", "transition_id"),
        ("captions", "caption_id"),
        ("markers", "marker_id"),
        ("template_instances", "template_instance_id"),
        ("groups", "group_id"),
        ("relationships", "relationship_id"),
    )
    for collection, id_field in collections:
        for position, item in enumerate(_list(timeline.get(collection))):
            if not isinstance(item, dict):
                continue
            identifier = register(item.get(id_field), f"/timeline/{collection}/{position}/{id_field}")
            if identifier:
                if collection == "groups":
                    index.groups[identifier] = item
                elif collection == "captions":
                    index.captions[identifier] = item
                elif collection == "template_instances":
                    index.template_instances[identifier] = item
    return index


def document_invariant_issues(
    document: dict[str, Any],
    index: IRIndex,
    *,
    workspace_id: str | None,
    registry: ProjectRegistry,
) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    if document.get("ir_version") != "video-project-ir.v1":
        problems.append(issue("ir_version_unsupported", "/ir_version", "Project IR version is unsupported."))
    metadata = _dict(document.get("metadata"))
    if workspace_id is not None and metadata.get("workspace_id") != workspace_id:
        problems.append(issue("workspace_mismatch", "/metadata/workspace_id", "Project IR belongs to another workspace."))
    _positive_int(_dict(document.get("canvas")).get("width"), "/canvas/width", problems)
    _positive_int(_dict(document.get("canvas")).get("height"), "/canvas/height", problems)
    color_space = _dict(document.get("canvas")).get("color_space")
    if color_space not in registry.color_spaces:
        problems.append(issue("color_space_not_allowed", "/canvas/color_space", "Color space is not allowlisted."))
    _validate_rational(_dict(document.get("canvas")).get("pixel_aspect"), "/canvas/pixel_aspect", problems)
    _validate_rational(document.get("frame_rate"), "/frame_rate", problems, positive_numerator=True)
    audio = _dict(document.get("audio"))
    sample_rate = audio.get("sample_rate")
    if sample_rate not in {32_000, 44_100, 48_000, 88_200, 96_000, 192_000}:
        problems.append(issue("sample_rate_not_allowed", "/audio/sample_rate", "Audio sample rate is not allowlisted."))
    if audio.get("channel_layout") not in CHANNEL_LAYOUTS:
        problems.append(issue("channel_layout_not_allowed", "/audio/channel_layout", "Audio channel layout is not allowlisted."))
    duration = document.get("duration_frames")
    if not _non_negative_integer(duration):
        problems.append(issue("duration_invalid", "/duration_frames", "Project duration must be a non-negative integer frame count."))
    for asset_pos, asset in enumerate(_list(document.get("assets"))):
        if isinstance(asset, dict):
            problems.extend(_asset_issues(asset, asset_pos, workspace_id))
    return problems


def _asset_issues(asset: dict[str, Any], position: int, workspace_id: str | None) -> list[ValidationIssue]:
    path = f"/assets/{position}"
    problems: list[ValidationIssue] = []
    if asset.get("kind") not in ASSET_KINDS:
        problems.append(issue("asset_kind_invalid", f"{path}/kind", "Asset kind is unsupported."))
    identity = _dict(asset.get("identity"))
    if set(identity) != {"storage_file_id", "source_version", "sha256"}:
        problems.append(issue("asset_identity_invalid", f"{path}/identity", "Asset identity must be a governed Storage identity."))
    if not isinstance(identity.get("storage_file_id"), str) or not IDENTIFIER.fullmatch(identity.get("storage_file_id", "")):
        problems.append(issue("storage_file_id_invalid", f"{path}/identity/storage_file_id", "Storage file id is invalid."))
    if not isinstance(identity.get("source_version"), str) or not identity.get("source_version"):
        problems.append(issue("source_version_invalid", f"{path}/identity/source_version", "Asset source version is required."))
    if not isinstance(identity.get("sha256"), str) or not SHA256.fullmatch(identity.get("sha256", "")):
        problems.append(issue("asset_digest_invalid", f"{path}/identity/sha256", "Asset SHA-256 is invalid."))
    provenance = _dict(asset.get("provenance"))
    if set(provenance) != {"provider_interface", "workspace_id", "acquisition"}:
        problems.append(issue("asset_provenance_invalid", f"{path}/provenance", "Asset provenance must use the governed provider profile."))
    if provenance.get("provider_interface") not in {"file.content.read", "file.media.stream"}:
        problems.append(issue("asset_provider_invalid", f"{path}/provenance/provider_interface", "Asset provider interface is not allowed."))
    if workspace_id is not None and provenance.get("workspace_id") != workspace_id:
        problems.append(issue("external_asset_reference", f"{path}/provenance/workspace_id", "Asset references another workspace."))
    source = _dict(asset.get("source"))
    _validate_rational(source.get("time_base"), f"{path}/source/time_base", problems, positive_numerator=True)
    duration_pts = source.get("duration_pts")
    if not _non_negative_integer(duration_pts):
        problems.append(issue("source_duration_invalid", f"{path}/source/duration_pts", "Source duration PTS must be non-negative."))
    duration_us = source.get("duration_us")
    if not _non_negative_integer(duration_us):
        problems.append(issue("source_duration_invalid", f"{path}/source/duration_us", "Source duration microseconds must be non-negative."))
    time_base = source.get("time_base")
    if _non_negative_integer(duration_pts) and _non_negative_integer(duration_us) and isinstance(time_base, dict):
        try:
            expected_duration_us = pts_to_microseconds(duration_pts, Rational.from_dict(time_base))
        except ValueError:
            pass
        else:
            if duration_us != expected_duration_us:
                problems.append(
                    issue(
                        "source_duration_mismatch",
                        f"{path}/source/duration_us",
                        "Source microsecond duration must equal its PTS/time-base conversion.",
                        expected=expected_duration_us,
                    )
                )
    if source.get("frame_rate_mode") not in {"cfr", "vfr", "still", "audio"}:
        problems.append(issue("frame_rate_mode_invalid", f"{path}/source/frame_rate_mode", "Source frame-rate mode is invalid."))
    pts_map = source.get("pts_map", [])
    if not isinstance(pts_map, list) or any(not _non_negative_integer(value) for value in pts_map):
        problems.append(issue("vfr_pts_invalid", f"{path}/source/pts_map", "VFR PTS map must contain non-negative integers."))
    elif pts_map != sorted(set(pts_map)):
        problems.append(issue("vfr_pts_not_monotonic", f"{path}/source/pts_map", "VFR PTS values must be strictly increasing."))
    elif _non_negative_integer(duration_pts) and any(value >= duration_pts for value in pts_map):
        problems.append(issue("vfr_pts_outside_source", f"{path}/source/pts_map", "VFR PTS values must precede source duration."))
    if source.get("frame_rate_mode") == "vfr" and not pts_map:
        problems.append(issue("vfr_pts_required", f"{path}/source/pts_map", "VFR sources require a PTS map."))
    return problems


def _validate_rational(value: object, path: str, problems: list[ValidationIssue], *, positive_numerator: bool = False) -> None:
    if not isinstance(value, dict):
        return
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    if not isinstance(numerator, int) or isinstance(numerator, bool) or not isinstance(denominator, int) or isinstance(denominator, bool):
        return
    if denominator <= 0 or (positive_numerator and numerator <= 0):
        problems.append(issue("rational_invalid", path, "Rational values require a positive denominator and rate."))
    elif gcd(abs(numerator), denominator) != 1:
        problems.append(issue("rational_not_normalized", path, "Rational values must be reduced to lowest terms."))


def _positive_int(value: object, path: str, problems: list[ValidationIssue]) -> None:
    if not _non_negative_integer(value) or value == 0:
        problems.append(issue("positive_integer_required", path, "Value must be a positive integer."))


def _non_negative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
