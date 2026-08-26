"""Canonical configuration fingerprints for hidden prepared sessions."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json

from core.runtime.runtime_session import RuntimeSessionRecord


_PREPARED_SESSION_FINGERPRINT_VERSION = 1


def prepared_session_fingerprint(body: Mapping[str, object], *, agent_id: str) -> str:
    """Hash only normalized session-creation configuration, never turn content."""
    payload = {
        "version": _PREPARED_SESSION_FINGERPRINT_VERSION,
        "agent_id": _text(agent_id),
        "agent_role_id": _text(body.get("agent_role_id")),
        "agent_type_id": _text(body.get("agent_type_id")),
        "project_id": _text(body.get("project_id")) or None,
        "source_app_id": _text(body.get("source_app_id")) or None,
        "system_prompt": _text(body.get("system_prompt")) or None,
        "skill_catalog_app_id": _text(body.get("skill_catalog_app_id")) or None,
        "skill_ids": _skill_ids(body.get("skill_ids")),
        "skill_activation_mode": _text(body.get("skill_activation_mode")) or "implicit",
        "requested_mode": _requested_mode(body.get("requested_mode")),
        "runtime_mode": _text(body.get("runtime_mode")) or "agentic",
        "routing_profile": _text(body.get("routing_profile")) or None,
        "hosted_provider_id": _text(body.get("hosted_provider_id")) or None,
        "hosted_model_id": _text(body.get("hosted_model_id")) or None,
        "workspace_profile_binding_id": _text(body.get("workspace_profile_binding_id")) or None,
        "reasoning_effort": _text(body.get("reasoning_effort")) or None,
        "title": _text(body.get("title")),
        "agent_label": _text(body.get("agent_label")),
    }
    return _fingerprint(payload)


def stored_prepared_session_configuration_key(session: RuntimeSessionRecord) -> str:
    """Return a deduplication key for new and pre-fingerprint prepared records."""
    if session.prepared_session_fingerprint:
        return f"request:{session.prepared_session_fingerprint}"
    binding = session.execution_binding
    payload = {
        "agent_id": session.agent_id,
        "agent_role_id": session.agent_role_id,
        "agent_type_id": session.agent_type_id,
        "project_id": session.project_id,
        "source_app_id": session.source_app_id,
        "system_prompt": session.system_prompt,
        "skill_catalog_app_id": session.skill_catalog_app_id,
        "skill_ids": session.skill_ids,
        "skill_activation_mode": session.skill_activation_mode,
        "requested_mode": session.requested_mode,
        "runtime_mode": session.runtime_mode,
        "hosted_provider_id": session.hosted_provider_id,
        "hosted_model_id": session.hosted_model_id,
        "thread_title": session.thread_title,
        "agent_label": session.agent_label,
        "binding": (
            {
                "workspace_binding_id": binding.workspace_binding_id,
                "profile_definition_id": binding.profile_definition_id,
                "model_id": binding.model_id,
                "reasoning_effort": binding.reasoning_effort,
            }
            if binding is not None
            else None
        ),
    }
    return f"legacy:{_fingerprint(payload)}"


def _fingerprint(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _requested_mode(value: object) -> str | None:
    normalized = _text(value)
    return normalized if normalized in {"sandbox", "full-access"} else None


def _skill_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [normalized for item in value if (normalized := _text(item))]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
