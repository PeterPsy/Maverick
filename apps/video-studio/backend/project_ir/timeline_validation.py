"""Transitions, captions, templates, markers, groups, and relationships."""

from __future__ import annotations

from typing import Any

from .errors import ValidationIssue, issue
from .invariants import IRIndex
from .registry import ProjectRegistry


RELATION_TYPES = {"linked-audio-video", "parent-child", "template-binding"}


def timeline_invariant_issues(
    document: dict[str, Any],
    index: IRIndex,
    registry: ProjectRegistry,
) -> list[ValidationIssue]:
    timeline = _dict(document.get("timeline"))
    duration = document.get("duration_frames")
    project_duration = duration if _integer(duration) and duration >= 0 else 0
    problems: list[ValidationIssue] = []
    problems.extend(_transition_issues(timeline, index, registry))
    problems.extend(_caption_issues(timeline, index, registry, project_duration))
    problems.extend(_marker_issues(timeline, project_duration))
    problems.extend(_template_issues(timeline, registry, project_duration))
    problems.extend(_group_issues(timeline, index))
    problems.extend(_relationship_issues(timeline, index))
    return problems


def _transition_issues(
    timeline: dict[str, Any],
    index: IRIndex,
    registry: ProjectRegistry,
) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    for position, transition in enumerate(_list(timeline.get("transitions"))):
        path = f"/timeline/transitions/{position}"
        required = {"transition_id", "registry", "from_clip_id", "to_clip_id", "duration_frames", "parameters"}
        if not isinstance(transition, dict) or set(transition) != required:
            problems.append(issue("transition_shape_invalid", path, "Transition fields do not match Project IR v1."))
            continue
        reference = _reference(transition.get("registry"))
        if reference not in registry.transitions:
            problems.append(issue("transition_not_registered", f"{path}/registry", "Transition is not registered."))
        from_id = transition.get("from_clip_id")
        to_id = transition.get("to_clip_id")
        before = index.clips.get(from_id) if isinstance(from_id, str) else None
        after = index.clips.get(to_id) if isinstance(to_id, str) else None
        if before is None:
            problems.append(issue("transition_clip_missing", f"{path}/from_clip_id", "Transition source clip is missing."))
        if after is None:
            problems.append(issue("transition_clip_missing", f"{path}/to_clip_id", "Transition target clip is missing."))
        if before is None or after is None:
            continue
        if index.clip_tracks.get(from_id) != index.clip_tracks.get(to_id):
            problems.append(issue("transition_track_mismatch", path, "Transition clips must share a compatible track."))
        before_start = before.get("start_frame")
        before_duration = before.get("duration_frames")
        after_start = after.get("start_frame")
        transition_duration = transition.get("duration_frames")
        if not all(_integer(value) for value in (before_start, before_duration, after_start, transition_duration)):
            continue
        if transition_duration <= 0 or transition_duration > min(before_duration, after.get("duration_frames", 0)):
            problems.append(issue("transition_duration_invalid", f"{path}/duration_frames", "Transition duration exceeds compatible clip handles."))
        if before_start > after_start or before_start + before_duration < after_start:
            problems.append(issue("transition_interval_incompatible", path, "Transition clips must be ordered and touch or overlap."))
        if reference == ("transition.cut", "1") and transition_duration != 1:
            problems.append(issue("transition_cut_duration", f"{path}/duration_frames", "Cut transition duration must be one frame."))
    return problems


def _caption_issues(
    timeline: dict[str, Any],
    index: IRIndex,
    registry: ProjectRegistry,
    project_duration: int,
) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    caption_tracks = {track_id for track_id, track_type in index.tracks.items() if track_type == "captions"}
    for position, caption in enumerate(_list(timeline.get("captions"))):
        path = f"/timeline/captions/{position}"
        required = {"caption_id", "track_id", "start_frame", "duration_frames", "text", "speaker", "style"}
        if not isinstance(caption, dict) or set(caption) != required:
            problems.append(issue("caption_shape_invalid", path, "Caption fields do not match Project IR v1."))
            continue
        start = caption.get("start_frame")
        duration = caption.get("duration_frames")
        if not _integer(start) or not _integer(duration) or start < 0 or duration <= 0 or start + duration > project_duration:
            problems.append(issue("caption_interval_invalid", path, "Caption interval must lie inside the project."))
        track_id = caption.get("track_id")
        if track_id not in caption_tracks:
            problems.append(issue("caption_track_missing", f"{path}/track_id", "Caption requires a captions track."))
        if not isinstance(caption.get("text"), str) or not caption.get("text"):
            problems.append(issue("caption_text_invalid", f"{path}/text", "Caption text must be non-empty plain text."))
        style = _dict(caption.get("style"))
        font = _dict(style.get("font"))
        if (font.get("id"), font.get("version")) not in registry.fonts:
            problems.append(issue("font_not_registered", f"{path}/style/font", "Caption font is not registered."))
    return problems


def _marker_issues(timeline: dict[str, Any], project_duration: int) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    for position, marker in enumerate(_list(timeline.get("markers"))):
        path = f"/timeline/markers/{position}"
        if not isinstance(marker, dict) or set(marker) != {"marker_id", "frame", "kind", "label", "note"}:
            problems.append(issue("marker_shape_invalid", path, "Marker fields do not match Project IR v1."))
            continue
        frame = marker.get("frame")
        if not _integer(frame) or frame < 0 or frame > project_duration:
            problems.append(issue("marker_outside_project", f"{path}/frame", "Marker must lie inside the project."))
        if marker.get("kind") not in {"marker", "chapter", "range-start", "range-end"}:
            problems.append(issue("marker_kind_invalid", f"{path}/kind", "Marker kind is unsupported."))
    return problems


def _template_issues(
    timeline: dict[str, Any],
    registry: ProjectRegistry,
    project_duration: int,
) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    for position, instance in enumerate(_list(timeline.get("template_instances"))):
        path = f"/timeline/template_instances/{position}"
        required = {"template_instance_id", "registry", "start_frame", "duration_frames", "parameters"}
        if not isinstance(instance, dict) or set(instance) != required:
            problems.append(issue("template_shape_invalid", path, "Template instance fields do not match Project IR v1."))
            continue
        if _reference(instance.get("registry")) not in registry.templates:
            problems.append(issue("template_not_registered", f"{path}/registry", "Template is not registered."))
        start = instance.get("start_frame")
        duration = instance.get("duration_frames")
        if not _integer(start) or not _integer(duration) or start < 0 or duration <= 0 or start + duration > project_duration:
            problems.append(issue("template_interval_invalid", path, "Template instance interval must lie inside the project."))
        if not isinstance(instance.get("parameters"), dict):
            problems.append(issue("template_parameters_invalid", f"{path}/parameters", "Template parameters must be an object."))
    return problems


def _group_issues(timeline: dict[str, Any], index: IRIndex) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    graph: dict[str, list[str]] = {}
    for position, group in enumerate(_list(timeline.get("groups"))):
        path = f"/timeline/groups/{position}"
        if not isinstance(group, dict) or set(group) != {"group_id", "name", "member_ids"}:
            problems.append(issue("group_shape_invalid", path, "Group fields do not match Project IR v1."))
            continue
        group_id = group.get("group_id")
        members = group.get("member_ids")
        if not isinstance(members, list) or not members:
            problems.append(issue("group_members_invalid", f"{path}/member_ids", "Group must contain at least one member."))
            continue
        group_edges: list[str] = []
        for member_pos, member_id in enumerate(members):
            if member_id not in index.clips and member_id not in index.groups:
                problems.append(issue("group_member_missing", f"{path}/member_ids/{member_pos}", "Group member reference is missing."))
            if member_id in index.groups:
                group_edges.append(member_id)
        if isinstance(group_id, str):
            graph[group_id] = group_edges
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(group_id: str) -> None:
        if group_id in visiting:
            problems.append(issue("group_cycle", index.id_paths.get(group_id, ""), "Group relationships must not contain cycles."))
            return
        if group_id in visited:
            return
        visiting.add(group_id)
        for child in sorted(graph.get(group_id, [])):
            visit(child)
        visiting.remove(group_id)
        visited.add(group_id)

    for group_id in sorted(graph):
        visit(group_id)
    return problems


def _relationship_issues(timeline: dict[str, Any], index: IRIndex) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    for position, relation in enumerate(_list(timeline.get("relationships"))):
        path = f"/timeline/relationships/{position}"
        if not isinstance(relation, dict) or set(relation) != {"relationship_id", "type", "source_id", "target_id"}:
            problems.append(issue("relationship_shape_invalid", path, "Relationship fields do not match Project IR v1."))
            continue
        if relation.get("type") not in RELATION_TYPES:
            problems.append(issue("relationship_type_invalid", f"{path}/type", "Relationship type is unsupported."))
        for field in ("source_id", "target_id"):
            if relation.get(field) not in index.id_paths:
                problems.append(issue("relationship_reference_missing", f"{path}/{field}", "Relationship endpoint is missing."))
        if relation.get("source_id") == relation.get("target_id"):
            problems.append(issue("relationship_self_reference", path, "Relationship endpoints must differ."))
    return problems


def _reference(value: object) -> tuple[str, str] | None:
    if not isinstance(value, dict) or set(value) != {"id", "version"}:
        return None
    identifier, version = value.get("id"), value.get("version")
    return (identifier, version) if isinstance(identifier, str) and isinstance(version, str) else None


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
