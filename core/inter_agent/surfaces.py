"""Shared payload helpers for inter-agent HTTP, CLI, and MCP surfaces."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from core.inter_agent.events import InterAgentEventPage, InterAgentEventRecord
from core.inter_agent.models import (
    AgentParticipantSnapshot,
    BudgetPolicySpec,
    EdgeSpec,
    InterAgentRunSpec,
    ParticipantSpec,
)
from core.inter_agent.store import InterAgentStore


def inter_agent_payload(value: Any) -> Any:
    """Return a JSON-safe payload for inter-agent dataclasses and records."""
    if is_dataclass(value):
        return inter_agent_payload(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): inter_agent_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [inter_agent_payload(item) for item in value]
    if isinstance(value, tuple):
        return [inter_agent_payload(item) for item in value]
    return value


def run_detail_payload(store: InterAgentStore, run) -> dict[str, Any]:
    """Return one run with its immediately useful F2 records."""
    return {
        "run": inter_agent_payload(run),
        "participants": inter_agent_payload(store.list_participants(run.run_id, workspace_id=run.workspace_id)),
        "edges": inter_agent_payload(store.list_edges(run.run_id, workspace_id=run.workspace_id)),
        "budget_policy": inter_agent_payload(store.get_budget_policy(run.budget_policy_id, workspace_id=run.workspace_id)),
        "budget_ledger": inter_agent_payload(store.get_budget_ledger(run.budget_ledger_id, workspace_id=run.workspace_id)),
    }


def execution_result_payload(store: InterAgentStore, result) -> dict[str, Any]:
    """Return one native executor result with refreshed run details."""
    return {
        **run_detail_payload(store, result.run),
        "participant_results": inter_agent_payload(result.participant_results),
        "root_runtime_events": inter_agent_payload(result.root_runtime_events),
        "final_answer": inter_agent_payload(getattr(result, "final_answer", "")),
    }


def event_page_payload(page: InterAgentEventPage) -> dict[str, Any]:
    """Return a JSON-safe event page payload."""
    return inter_agent_payload(
        {
            "items": page.events,
            "visibility_plane": page.visibility_plane,
            "limit": page.limit,
            "after_event_id": page.after_event_id,
            "before_event_id": page.before_event_id,
            "has_more_before": page.has_more_before,
            "has_more_after": page.has_more_after,
            "oldest_event_id": page.oldest_event_id,
            "newest_event_id": page.newest_event_id,
        }
    )


def artifact_items_payload(events: list[InterAgentEventRecord]) -> list[dict[str, Any]]:
    """Return artifact records projected from inter-agent artifact events."""
    artifacts: list[dict[str, Any]] = []
    for event in events:
        if event.event_type != "inter_agent.artifact.created":
            continue
        refs = event.payload.get("artifact_refs")
        if not isinstance(refs, list):
            refs = []
        for index, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            item = {str(key): inter_agent_payload(value) for key, value in ref.items()}
            item.setdefault("artifact_id", _artifact_id(event, item, index))
            item.setdefault("label", _artifact_label(item, index))
            item["event_id"] = event.event_id
            item["run_id"] = event.run_id
            item["participant_id"] = event.participant_id
            item["created_at"] = inter_agent_payload(event.created_at)
            item["status"] = str(event.payload.get("status") or item.get("status") or "created")
            partial_output = event.payload.get("partial_output")
            if isinstance(partial_output, str) and partial_output.strip():
                item["partial_output"] = partial_output
            artifacts.append(item)
    return artifacts


def run_spec_from_payload(
    payload: dict[str, Any],
    *,
    workspace_id: str,
    created_by_user_id: str,
    source_app_id: str = "chat",
    allow_materialized_authority: bool = False,
    allow_agent_snapshots: bool = False,
) -> InterAgentRunSpec:
    """Build an InterAgentRunSpec from a public surface payload.

    Public HTTP/CLI/MCP callers may choose topology and budget, but prompt,
    skill, source-app, provider, and authority materialization must come from
    core policy or an authorized Agents snapshot. Those fields are therefore
    ignored unless an internal caller explicitly opts into trusted materialized
    authority.
    """
    participants = [
        participant_spec_from_payload(
            item,
            allow_materialized_authority=allow_materialized_authority,
            allow_agent_snapshots=allow_agent_snapshots or allow_materialized_authority,
        )
        for item in _list_of_dicts(payload.get("participants"))
    ]
    edges = [edge_spec_from_payload(item) for item in _list_of_dicts(payload.get("edges"))]
    budget_payload = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    return InterAgentRunSpec(
        workspace_id=workspace_id,
        thread_id=_text(payload.get("thread_id")) or _text(payload.get("root_runtime_session_id")),
        root_runtime_session_id=_text(payload.get("root_runtime_session_id")),
        source_app_id=_text(source_app_id) or "chat",
        mode=_text(payload.get("mode")) or "manager_tools",  # type: ignore[arg-type]
        created_by_user_id=created_by_user_id,
        participants=participants,
        budget=budget_policy_spec_from_payload(budget_payload),
        edges=edges,
        run_id=_text(payload.get("run_id")) or None,
        orchestrator_participant_id=_text(payload.get("orchestrator_participant_id")) or None,
        aggregator_participant_id=_text(payload.get("aggregator_participant_id")) or None,
        merge_policy=_text(payload.get("merge_policy")) or None,
        visibility_level=_text(payload.get("visibility_level")) or "summary",  # type: ignore[arg-type]
        idempotency_key=_text(payload.get("idempotency_key")) or None,
        source_runtime_turn_id=_text(payload.get("source_runtime_turn_id")) or None,
        orchestration_policy=_text(payload.get("orchestration_policy")) or None,
    )


def _artifact_id(event: InterAgentEventRecord, item: dict[str, Any], index: int) -> str:
    for key in ("file_id", "workspace_relative_path", "relative_path", "id", "artifact_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{event.event_id}:{index}"


def _artifact_label(item: dict[str, Any], index: int) -> str:
    for key in ("label", "name", "filename", "title", "workspace_relative_path", "relative_path"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"Artifact {index + 1}"


def participant_spec_from_payload(
    payload: dict[str, Any],
    *,
    allow_materialized_authority: bool = False,
    allow_agent_snapshots: bool = False,
) -> ParticipantSpec:
    """Build a participant spec from one surface payload item."""
    agent_snapshot = None
    prompt_snapshot_ref = None
    skill_ids: list[str] = []
    provider_id = None
    authority_grant_ids: list[str] = []
    if allow_agent_snapshots or allow_materialized_authority:
        agent_snapshot = agent_snapshot_from_payload(payload.get("agent_snapshot"))
    if allow_materialized_authority:
        prompt_snapshot_ref = _text(payload.get("prompt_snapshot_ref")) or None
        skill_ids = _string_list(payload.get("skill_ids"))
        provider_id = _text(payload.get("provider_id")) or None
        authority_grant_ids = _string_list(payload.get("authority_grant_ids"))
    return ParticipantSpec(
        participant_id=_text(payload.get("participant_id")) or None,
        kind=_text(payload.get("kind")),  # type: ignore[arg-type]
        execution_mode=_text(payload.get("execution_mode")),  # type: ignore[arg-type]
        label=_text(payload.get("label")),
        agent_type_id=_text(payload.get("agent_type_id")) or None,
        agent_snapshot=agent_snapshot,
        prompt_snapshot_ref=prompt_snapshot_ref,
        skill_ids=skill_ids,
        provider_id=provider_id,
        authority_grant_ids=authority_grant_ids,
        thread_visibility=(_text(payload.get("thread_visibility")) or None),  # type: ignore[arg-type]
    )


def agent_snapshot_from_payload(payload: Any) -> AgentParticipantSnapshot | None:
    """Build a materialized agent snapshot when one was supplied."""
    if not isinstance(payload, dict):
        return None
    return AgentParticipantSnapshot(
        agent_type_id=_text(payload.get("agent_type_id")),
        label=_text(payload.get("label")),
        system_prompt=_text(payload.get("system_prompt")),
        skill_ids=_string_list(payload.get("skill_ids")),
        skill_catalog_app_id=_text(payload.get("skill_catalog_app_id")),
        provider_id=_text(payload.get("provider_id")) or None,
        revision_id=_text(payload.get("revision_id")) or None,
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )


def edge_spec_from_payload(payload: dict[str, Any]) -> EdgeSpec:
    """Build one edge spec from a surface payload item."""
    return EdgeSpec(
        source_id=_text(payload.get("source_id")),
        target_id=_text(payload.get("target_id")),
        kind=_text(payload.get("kind")),  # type: ignore[arg-type]
        label=_text(payload.get("label")),
    )


def budget_policy_spec_from_payload(payload: dict[str, Any]) -> BudgetPolicySpec:
    """Build a budget policy spec using model defaults for omitted fields."""
    return BudgetPolicySpec(
        max_participants=_int(payload.get("max_participants"), default=1),
        max_concurrent_participants=_int(payload.get("max_concurrent_participants"), default=1),
        max_handoffs=_int(payload.get("max_handoffs"), default=0),
        max_rounds=_int(payload.get("max_rounds"), default=1),
        max_total_turns=_int(payload.get("max_total_turns"), default=1),
        max_turns_per_participant=_int(payload.get("max_turns_per_participant"), default=1),
        max_tool_calls=_int(payload.get("max_tool_calls"), default=0),
        max_estimated_tokens=_int(payload.get("max_estimated_tokens"), default=0),
        max_estimated_cost=Decimal(str(payload.get("max_estimated_cost") or "0")),
        max_idle_seconds=_int(payload.get("max_idle_seconds"), default=300),
        max_stall_seconds=_int(payload.get("max_stall_seconds"), default=300),
        approval_required_above_cost=Decimal(str(payload.get("approval_required_above_cost") or "0")),
    )


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)
