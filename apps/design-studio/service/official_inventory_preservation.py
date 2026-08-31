"""Redaction-safe user-content claims for official OpenDesign migrations."""

from __future__ import annotations

from typing import Any

from official_inventory_values import canonical_digest


VOLATILE_FIELDS = {
    "createdAt",
    "updatedAt",
    "startedAt",
    "endedAt",
    "mtime",
    "pid",
    "resolvedDir",
    "eventsLogPath",
}
SERVER_OWNED_RECORD_FIELDS = {*VOLATILE_FIELDS, "metadata"}


def preservation_claim_sets(
    records: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    """Return field-level claims whose subset must survive an upstream migration.

    Claims bind each protected scalar to its native record identity and field
    path. A candidate may add schema fields or records without invalidating old
    claims, while deletion or mutation of an existing user value loses the
    corresponding claim. Project metadata is functional OpenDesign state, so
    only its explicitly volatile server fields are removed. Bundled Design
    Systems remain release-owned rather than user-owned migration content.
    """
    return {
        category: sorted(
            claim
            for record in category_records
            for claim in _record_claims(category, record)
        )
        for category, category_records in records.items()
    }


def _record_claims(category: str, record: dict[str, Any]) -> list[str]:
    identity, content = _protected_projection(category, record)
    if content is None:
        return []
    return [
        canonical_digest(["preserved-content-claim-v2", category, identity, path, value])
        for path, value in _claim_nodes(content)
    ]


def _protected_projection(
    category: str,
    record: dict[str, Any],
) -> tuple[dict[str, Any], Any | None]:
    if category == "projects":
        return (
            {"id": record.get("id")},
            _without(record, {"id", *VOLATILE_FIELDS}),
        )
    if category == "conversations":
        conversation = _dict(record.get("conversation"))
        return (
            {
                "project_id": record.get("project_id"),
                "conversation_id": conversation.get("id"),
            },
            _without(
                conversation,
                {"id", "projectId", "runId", "status", *SERVER_OWNED_RECORD_FIELDS},
            ),
        )
    if category == "ordered_messages":
        message = _dict(record.get("message"))
        return (
            {
                "project_id": record.get("project_id"),
                "conversation_id": record.get("conversation_id"),
                "message_id": message.get("id"),
                "order": record.get("order"),
            },
            _stable_message_content(
                message,
            ),
        )
    if category == "design_systems":
        summary = _dict(record.get("summary"))
        identity = {"source": summary.get("source"), "id": summary.get("id")}
        if summary.get("source") == "built-in":
            return identity, None
        return identity, {
            "summary": _without(summary, {"id", "source", *SERVER_OWNED_RECORD_FIELDS}),
            "detail": _without(_dict(record.get("detail")), SERVER_OWNED_RECORD_FIELDS),
            "files": _clean(record.get("files")),
        }
    if category == "project_files":
        return (
            {"project_id": record.get("project_id"), "name": record.get("name")},
            {"body_sha256": record.get("body_sha256")},
        )
    if category == "artifacts":
        if "manifest" in record:
            return (
                {
                    "kind": "file-manifest",
                    "project_id": record.get("project_id"),
                    "name": record.get("name"),
                },
                _clean(record.get("manifest")),
            )
        summary = _dict(record.get("summary"))
        detail = _dict(record.get("detail"))
        artifact = _dict(detail.get("artifact"))
        return (
            {
                "kind": "live-artifact",
                "project_id": record.get("project_id"),
                "id": summary.get("id") or artifact.get("id") or detail.get("id"),
            },
            {
                "summary": _without(summary, {"id", *SERVER_OWNED_RECORD_FIELDS}),
                "detail": _without(detail, {"id", *SERVER_OWNED_RECORD_FIELDS}),
                "template_sha256": record.get("template_sha256"),
                "rendered_sha256": record.get("rendered_sha256"),
            },
        )
    if category == "settings":
        return {"id": "app-config"}, _clean(record)
    if category == "run_references":
        return {"reference": record}, None
    raise ValueError(f"unsupported preservation category: {category}")


def _without(value: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {
        key: _clean(item)
        for key, item in value.items()
        if key not in excluded
    }


def _stable_message_content(message: dict[str, Any]) -> dict[str, Any]:
    content = _without(
        message,
        {
            "id",
            "runId",
            "runStatus",
            "lastRunEventId",
            "status",
            *SERVER_OWNED_RECORD_FIELDS,
        },
    )
    events = content.get("events")
    if isinstance(events, list):
        content["events"] = _coalesce_adjacent_text_events(events)
    return content


def _coalesce_adjacent_text_events(events: list[Any]) -> list[Any]:
    """Ignore transport chunk boundaries while preserving the exact text stream."""
    normalized: list[Any] = []
    for event in events:
        if _plain_text_event(event) and normalized and _plain_text_event(normalized[-1]):
            previous = normalized[-1]
            normalized[-1] = {
                "kind": "text",
                "text": previous["text"] + event["text"],
            }
        else:
            normalized.append(event)
    return normalized


def _plain_text_event(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"kind", "text"}
        and value.get("kind") == "text"
        and isinstance(value.get("text"), str)
    )


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return _without(value, VOLATILE_FIELDS)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _claim_nodes(value: Any, path: tuple[str, ...] = ()) -> list[tuple[list[str], Any]]:
    if isinstance(value, dict):
        claims = [(list(path), {"container": "object"})]
        for key in sorted(value):
            claims.extend(_claim_nodes(value[key], (*path, key)))
        return claims
    if isinstance(value, list):
        claims = [(list(path), {"container": "array"})]
        for index, item in enumerate(value):
            claims.extend(_claim_nodes(item, (*path, str(index))))
        return claims
    return [(list(path), {"scalar": value})]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = ["preservation_claim_sets"]
