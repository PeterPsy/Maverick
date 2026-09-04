"""Canonical configuration fingerprints for hidden prepared sessions."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json

from core.runtime.runtime_session import RuntimeSessionRecord


_PREPARED_SESSION_FINGERPRINT_VERSION = 3


def prepared_session_fingerprint(
    body: Mapping[str, object],
    *,
    agent_id: str,
    execution_binding: object | None = None,
    hosted_text_binding: object | None = None,
) -> str:
    """Hash normalized requested and resolved configuration, never turn content."""
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
        "execution_binding": _resolved_execution_binding(execution_binding),
        "hosted_text_binding": _resolved_hosted_text_binding(
            hosted_text_binding
        ),
        "workspace_profile_binding_id": (
            _text(getattr(execution_binding, "workspace_binding_id", None))
            or _text(body.get("workspace_profile_binding_id"))
            or None
        ),
        "reasoning_effort": (
            _text(getattr(execution_binding, "reasoning_effort", None))
            or _text(body.get("reasoning_effort"))
            or None
        ),
        "title": _text(body.get("title")),
        "agent_label": _text(body.get("agent_label")),
    }
    return _fingerprint(payload)


def _resolved_execution_binding(binding: object | None) -> dict[str, object] | None:
    if binding is None:
        return None
    return {
        "profile_definition_id": _text(getattr(binding, "profile_definition_id", None)),
        "profile_definition_revision": _text(
            getattr(binding, "profile_definition_revision", None)
        ),
        "workspace_binding_id": _text(getattr(binding, "workspace_binding_id", None)),
        "workspace_binding_revision": getattr(binding, "workspace_binding_revision", None),
        "runtime_engine_id": _text(getattr(binding, "runtime_engine_id", None)),
        "model_provider_id": _text(getattr(binding, "model_provider_id", None)),
        "model_id": _text(getattr(binding, "model_id", None)),
        "reasoning_effort": _text(getattr(binding, "reasoning_effort", None)) or None,
        "execution_mode": _text(getattr(binding, "execution_mode", None)),
    }


def _resolved_hosted_text_binding(binding: object | None) -> dict[str, object] | None:
    if binding is None:
        return None
    profile = getattr(binding, "profile", None)
    return {
        "profile_id": _text(getattr(profile, "profile_id", None)),
        "profile_revision": _text(getattr(profile, "revision", None)),
        "provider_id": _text(getattr(profile, "provider_id", None)),
        "model_id": _text(getattr(profile, "model_id", None)),
        "provider_routing_digest": _text(
            getattr(binding, "provider_routing_digest", None)
        ),
    }


def stored_prepared_session_configuration_key(session: RuntimeSessionRecord) -> str:
    """Return a deduplication key for new and pre-fingerprint prepared records."""
    if session.prepared_session_fingerprint:
        return f"request:{session.prepared_session_fingerprint}"
    binding = session.execution_binding
    text_binding = session.hosted_text_binding
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
        "hosted_text_binding": (
            {
                "profile_id": text_binding.profile.profile_id,
                "profile_revision": text_binding.profile.revision,
                "provider_id": text_binding.provider_id,
                "model_id": text_binding.model_id,
                "provider_routing_digest": text_binding.provider_routing_digest,
            }
            if text_binding is not None
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
