"""Deterministic Project IR v1 validation orchestration."""

from __future__ import annotations

from typing import Any

from .canonical import CanonicalizationError, canonical_bytes
from .clip_validation import clip_invariant_issues
from .errors import IRValidationError, ValidationIssue, issue
from .invariants import build_index, document_invariant_issues
from .models import ValidationLimits
from .registry import ProjectRegistry, default_registry
from .security import security_issues
from .structure import structural_issues
from .timeline_validation import timeline_invariant_issues


def validate_project_ir(
    document: object,
    *,
    workspace_id: str | None = None,
    registry: ProjectRegistry | None = None,
    limits: ValidationLimits | None = None,
) -> None:
    """Validate Project IR, rejecting bounded-resource failures before deep work."""

    active_registry = registry or default_registry()
    active_limits = limits or ValidationLimits()
    try:
        size = len(canonical_bytes(document))
    except CanonicalizationError as error:
        raise IRValidationError([issue("canonical_json_invalid", "", str(error))]) from error
    if size > active_limits.max_document_bytes:
        raise IRValidationError(
            [
                issue(
                    "document_limit_exceeded",
                    "",
                    "Project IR exceeds the configured canonical byte limit.",
                    actual=size,
                    maximum=active_limits.max_document_bytes,
                )
            ]
        )
    if isinstance(document, dict):
        bounded_resource_problems = _complexity_issues(document, active_limits)
        if bounded_resource_problems:
            raise IRValidationError(bounded_resource_problems)
    problems: list[ValidationIssue] = []
    problems.extend(structural_issues(document))
    problems.extend(security_issues(document))
    if isinstance(document, dict):
        index = build_index(document, problems)
        problems.extend(
            document_invariant_issues(
                document,
                index,
                workspace_id=workspace_id,
                registry=active_registry,
            )
        )
        problems.extend(clip_invariant_issues(document, index, active_registry))
        problems.extend(timeline_invariant_issues(document, index, active_registry))
    if problems:
        raise IRValidationError(problems)


def _complexity_issues(
    document: dict[str, Any],
    limits: ValidationLimits,
) -> list[ValidationIssue]:
    timeline = document.get("timeline") if isinstance(document.get("timeline"), dict) else {}
    tracks = _list(timeline.get("tracks"))
    clips = [clip for track in tracks if isinstance(track, dict) for clip in _list(track.get("clips"))]
    layers = [layer for clip in clips if isinstance(clip, dict) for layer in _list(clip.get("layers"))]
    effects = [effect for clip in clips if isinstance(clip, dict) for effect in _list(clip.get("effects"))]
    effects.extend(
        effect for layer in layers if isinstance(layer, dict) for effect in _list(layer.get("effects"))
    )
    keyframes = [key for clip in clips if isinstance(clip, dict) for key in _list(clip.get("keyframes"))]
    counts = {
        "/timeline/tracks": (len(tracks), limits.max_tracks, "track"),
        "/timeline": (len(clips), limits.max_clips, "clip"),
        "/timeline/layers": (len(layers), limits.max_layers, "layer"),
        "/timeline/keyframes": (len(keyframes), limits.max_keyframes, "keyframe"),
        "/timeline/effects": (len(effects), limits.max_effects, "effect"),
        "/timeline/transitions": (
            len(_list(timeline.get("transitions"))),
            limits.max_transitions,
            "transition",
        ),
        "/timeline/captions": (len(_list(timeline.get("captions"))), limits.max_captions, "caption"),
        "/timeline/markers": (len(_list(timeline.get("markers"))), limits.max_markers, "marker"),
        "/timeline/groups": (len(_list(timeline.get("groups"))), limits.max_groups, "group"),
    }
    problems: list[ValidationIssue] = []
    for path, (actual, maximum, kind) in sorted(counts.items()):
        if actual > maximum:
            problems.append(
                issue(
                    "complexity_limit_exceeded",
                    path,
                    f"Project IR exceeds the configured {kind} limit.",
                    actual=actual,
                    maximum=maximum,
                )
            )
    text_characters = _text_characters(document)
    if text_characters > limits.max_text_characters:
        problems.append(
            issue(
                "text_limit_exceeded",
                "/timeline",
                "Project IR exceeds the configured text character limit.",
                actual=text_characters,
                maximum=limits.max_text_characters,
            )
        )
    return problems


def _text_characters(value: object, *, parent_key: str = "") -> int:
    if isinstance(value, str):
        return len(value) if parent_key in {"plain_text", "text", "label", "note", "name"} else 0
    if isinstance(value, list):
        return sum(_text_characters(item, parent_key=parent_key) for item in value)
    if isinstance(value, dict):
        return sum(_text_characters(item, parent_key=str(key)) for key, item in value.items())
    return 0


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
