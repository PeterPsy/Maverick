"""Presentation-only migration of legacy provider selection records."""

from __future__ import annotations

from urllib.parse import quote

from core.providers.execution_families import (
    HOSTED_TEXT_EXECUTION_FAMILY,
    NATIVE_AGENT_EXECUTION_FAMILY,
)


EXECUTION_FAMILY_SELECTION_SCHEMA = "maverick.execution-family-selection.v1"


def execution_family_selection_migration_payload(
    *,
    runtime_selection,
    hosted_selection,
    agentic_profile_items: list[dict[str, object]],
) -> dict[str, object]:
    """Map old records to UI identities without writing them or pinned sessions."""
    records: list[dict[str, object]] = []
    if runtime_selection is not None:
        matching_profile = next(
            (
                item
                for item in agentic_profile_items
                if item.get("runtime_engine_id") == runtime_selection.provider_id
                and (
                    not runtime_selection.model_id
                    or item.get("model_id") == runtime_selection.model_id
                )
                and bool(item.get("is_default"))
            ),
            None,
        )
        family = (
            str(matching_profile.get("execution_family") or "")
            if matching_profile is not None
            else (
                NATIVE_AGENT_EXECUTION_FAMILY
                if runtime_selection.provider_id == "codex"
                else ""
            )
        )
        if matching_profile is not None:
            canonical_id = str(matching_profile.get("runtime_engine_id") or "")
        else:
            canonical_id = runtime_selection.provider_id
        records.append(
            _record(
                source_kind="provider_selection",
                source_profile=runtime_selection.selection_scope,
                source_id=runtime_selection.selection_id,
                execution_family=family,
                canonical_selection_id=canonical_id,
            )
        )
    if hosted_selection is not None:
        model_id = str(hosted_selection.model_id or "")
        canonical_id = (
            f"hosted:{hosted_selection.provider_id}:{quote(model_id, safe='')}"
            if model_id
            else hosted_selection.provider_id
        )
        records.append(
            _record(
                source_kind="hosted_provider_selection",
                source_profile=hosted_selection.profile,
                source_id=hosted_selection.selection_id,
                execution_family=HOSTED_TEXT_EXECUTION_FAMILY,
                canonical_selection_id=canonical_id,
            )
        )
    return {
        "schema_version": EXECUTION_FAMILY_SELECTION_SCHEMA,
        "mode": "projection_only",
        "persisted_records_mutated": False,
        "pinned_sessions_rewritten": False,
        "records": records,
        "legacy_labels": [
            {
                "label": "Agentic models",
                "replacement": "family-derived",
            },
            {
                "label": "Hosted text model settings",
                "replacement": "Text-only Models (API)",
            },
            {
                "label": "Hosted chat / fast model",
                "replacement": "Text-only Models (API)",
            },
        ],
    }


def _record(
    *,
    source_kind: str,
    source_profile: str,
    source_id: str,
    execution_family: str,
    canonical_selection_id: str,
) -> dict[str, object]:
    return {
        "source_kind": source_kind,
        "source_profile": source_profile,
        "source_id": source_id,
        "execution_family": execution_family or None,
        "canonical_selection_id": canonical_selection_id or None,
        "storage_action": "preserved",
    }


__all__ = [
    "EXECUTION_FAMILY_SELECTION_SCHEMA",
    "execution_family_selection_migration_payload",
]
