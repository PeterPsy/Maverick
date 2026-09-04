"""Immutable profile, status, certificate, and session pin for text-only APIs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import json
from typing import Literal, Mapping
from uuid import uuid4

from core.providers.errors import ProviderError
from core.providers.execution_families import HOSTED_TEXT_EXECUTION_FAMILY
from core.providers.models import ProviderDefinition, ProviderModelOption
from core.runtime.execution_binding import canonical_digest


HostedTextProfileState = Literal["available", "disabled", "unavailable"]


@dataclass(frozen=True)
class HostedTextProfileDefinition:
    """Exact provider/model text profile with no agentic authority."""

    profile_id: str
    revision: str
    display_name: str
    execution_family: Literal["hosted_text"]
    provider_id: str
    model_id: str
    model_revision: str | None
    model_revision_policy: Literal["exact", "provider_alias"]
    provider_protocol: str
    provider_api_version: str | None
    endpoint_id: str
    input_modalities: tuple[str, ...]
    output_modalities: tuple[str, ...]
    context_limit_tokens: int | None
    output_limit_tokens: int | None
    cost_policy: str
    retention_policy: str
    data_destination: str


@dataclass(frozen=True)
class HostedTextProfileStatus:
    """Availability is independent from immutable profile identity."""

    profile_id: str
    profile_revision: str
    status: HostedTextProfileState
    reason_code: str | None


@dataclass(frozen=True)
class HostedTextCapabilityCertificate:
    """Text-only capability statement, never an agentic certificate."""

    certificate_id: str
    certificate_kind: Literal["hosted_text_capability"]
    profile_id: str
    profile_revision: str
    profile_digest: str
    text_generation: Literal[True]
    workspace_tools: Literal[False]
    action_loop: Literal[False]
    workspace_actions: Literal[False]


@dataclass(frozen=True)
class HostedTextExecutionBinding:
    """Self-digesting session pin for one text-only provider route."""

    binding_id: str
    session_id: str
    workspace_id: str
    profile: HostedTextProfileDefinition
    status: HostedTextProfileStatus
    certificate: HostedTextCapabilityCertificate
    provider_routing_snapshot: dict[str, object]
    provider_routing_digest: str
    binding_digest: str
    created_at: datetime
    legacy_inferred: bool = False

    @property
    def provider_id(self) -> str:
        return self.profile.provider_id

    @property
    def model_id(self) -> str:
        return self.profile.model_id


def build_hosted_text_profile(
    definition: ProviderDefinition,
    model: ProviderModelOption,
) -> tuple[
    HostedTextProfileDefinition,
    HostedTextProfileStatus,
    HostedTextCapabilityCertificate,
]:
    """Derive a separate immutable text profile from server-owned metadata."""
    if definition.provider_role != "model_provider":
        raise ProviderError("hosted_text_provider_role_invalid")
    output_modalities = tuple(model.output_modalities or ["text"])
    if "text" not in output_modalities:
        raise ProviderError("hosted_text_model_output_unsupported")
    metadata = dict(model.metadata)
    protocol = str(
        metadata.get("protocol")
        or getattr(definition.execution_contract, "request_shape", "")
        or "hosted-text-generation"
    )
    api_version = str(metadata.get("api_version") or "").strip() or None
    endpoint_id = str(
        metadata.get("endpoint")
        or _first_network_host(definition)
        or definition.provider_id
    )
    model_revision = str(metadata.get("model_revision") or "").strip() or None
    identity = {
        "provider_id": definition.provider_id,
        "model_id": model.model_id,
        "model_revision": model_revision,
        "provider_protocol": protocol,
        "provider_api_version": api_version,
        "endpoint_id": endpoint_id,
        "input_modalities": tuple(model.input_modalities or ["text"]),
        "output_modalities": output_modalities,
        "context_limit_tokens": _model_limit(model, "context_length"),
        "output_limit_tokens": _model_limit(
            model,
            "max_output_tokens",
            "max_completion_tokens",
        ),
        "cost_metadata": definition.cost_metadata,
        "retention_policy": _retention_policy(definition),
    }
    revision = canonical_digest(identity)
    profile = HostedTextProfileDefinition(
        profile_id=(
            f"hosted-text-profile:{definition.provider_id}:"
            f"{canonical_digest(model.model_id)[:16]}"
        ),
        revision=revision,
        display_name=f"{definition.label} · {model.label}",
        execution_family=HOSTED_TEXT_EXECUTION_FAMILY,
        provider_id=definition.provider_id,
        model_id=model.model_id,
        model_revision=model_revision,
        model_revision_policy="exact" if model_revision else "provider_alias",
        provider_protocol=protocol,
        provider_api_version=api_version,
        endpoint_id=endpoint_id,
        input_modalities=tuple(model.input_modalities or ["text"]),
        output_modalities=output_modalities,
        context_limit_tokens=_model_limit(model, "context_length"),
        output_limit_tokens=_model_limit(
            model,
            "max_output_tokens",
            "max_completion_tokens",
        ),
        cost_policy=canonical_digest(definition.cost_metadata),
        retention_policy=_retention_policy(definition),
        data_destination=_data_destination(definition),
    )
    profile_digest = canonical_digest(profile)
    state: HostedTextProfileState = (
        "available" if definition.status == "active" else "disabled"
    )
    status = HostedTextProfileStatus(
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        status=state,
        reason_code=None if state == "available" else "provider_disabled",
    )
    certificate = HostedTextCapabilityCertificate(
        certificate_id=(
            f"hosted-text-certificate:{definition.provider_id}:"
            f"{canonical_digest((profile.profile_id, profile.revision))[:16]}"
        ),
        certificate_kind="hosted_text_capability",
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile_digest,
        text_generation=True,
        workspace_tools=False,
        action_loop=False,
        workspace_actions=False,
    )
    return profile, status, certificate


def pin_hosted_text_execution_binding(
    state,
    *,
    session_id: str,
    workspace_id: str,
    hosted_provider_id: str | None,
    hosted_model_id: str | None,
    now: datetime | None = None,
) -> HostedTextExecutionBinding:
    """Resolve and pin a text route before session persistence."""
    from core.providers.routing import (
        ProviderRoutingContext,
        primary_routing_failure_reason,
        select_provider_for_profile,
    )
    from core.providers.service import effective_provider_registry

    registry = effective_provider_registry(
        state.provider_store,
        registry=getattr(state, "provider_registry", None),
    )
    decision = select_provider_for_profile(
        "plain_hosted_chat",
        ProviderRoutingContext(
            workspace_id=workspace_id,
            provider_store=state.provider_store,
            registry=registry,
            secret_store=state.secret_store,
            hosted_provider_id=str(hosted_provider_id or "").strip() or None,
            hosted_model_id=str(hosted_model_id or "").strip() or None,
        ),
    )
    if (
        decision.execution_path != "plain_hosted_text"
        or not decision.selected_provider_id
        or not decision.selected_model_id_or_voice_id
    ):
        raise ProviderError(primary_routing_failure_reason(decision))
    definition = registry.get_provider_definition(decision.selected_provider_id)
    model = next(
        (
            option
            for option in definition.model_options
            if option.model_id == decision.selected_model_id_or_voice_id
        ),
        None,
    )
    if model is None:
        raise ProviderError("hosted_text_model_unavailable")
    profile, status, certificate = build_hosted_text_profile(definition, model)
    if status.status != "available":
        raise ProviderError(status.reason_code or "hosted_text_profile_unavailable")
    routing_snapshot = _provider_routing_snapshot(
        state.provider_store,
        workspace_id=workspace_id,
        provider_id=profile.provider_id,
        model_id=profile.model_id,
    )
    timestamp = now or datetime.now(tz=UTC)
    binding = HostedTextExecutionBinding(
        binding_id=f"hosted-text-binding-{uuid4().hex}",
        session_id=session_id,
        workspace_id=workspace_id,
        profile=profile,
        status=status,
        certificate=certificate,
        provider_routing_snapshot=routing_snapshot,
        provider_routing_digest=canonical_digest(routing_snapshot),
        binding_digest="",
        created_at=timestamp,
    )
    return replace(binding, binding_digest=canonical_digest(binding))


def fork_hosted_text_execution_binding(
    binding: HostedTextExecutionBinding,
    *,
    session_id: str,
    created_at: datetime,
) -> HostedTextExecutionBinding:
    """Fork a continuation without changing its provider/model family pin."""
    forked = replace(
        binding,
        binding_id=f"hosted-text-binding-{uuid4().hex}",
        session_id=session_id,
        binding_digest="",
        created_at=created_at,
    )
    return replace(forked, binding_digest=canonical_digest(forked))


def hosted_text_binding_from_document(
    document: Mapping[str, object],
) -> HostedTextExecutionBinding:
    """Hydrate and verify one stored text-only session binding."""
    payload = dict(document)
    profile_document = payload.get("profile")
    status_document = payload.get("status")
    certificate_document = payload.get("certificate")
    if not all(
        isinstance(item, Mapping)
        for item in (profile_document, status_document, certificate_document)
    ):
        raise ValueError("Hosted text execution binding is incomplete.")
    profile_payload = dict(profile_document)  # type: ignore[arg-type]
    profile_payload["input_modalities"] = tuple(profile_payload["input_modalities"])
    profile_payload["output_modalities"] = tuple(profile_payload["output_modalities"])
    payload["profile"] = HostedTextProfileDefinition(**profile_payload)
    payload["status"] = HostedTextProfileStatus(**dict(status_document))  # type: ignore[arg-type]
    payload["certificate"] = HostedTextCapabilityCertificate(
        **dict(certificate_document)  # type: ignore[arg-type]
    )
    payload["provider_routing_snapshot"] = _json_snapshot(
        payload.get("provider_routing_snapshot")
    )
    payload.setdefault("legacy_inferred", False)
    binding = HostedTextExecutionBinding(**payload)
    _validate_hosted_text_binding(binding)
    return binding


def validate_hosted_text_execution_binding(
    binding: HostedTextExecutionBinding,
) -> None:
    """Validate an in-memory binding before every provider dispatch."""
    _validate_hosted_text_binding(binding)


def _validate_hosted_text_binding(binding: HostedTextExecutionBinding) -> None:
    profile = binding.profile
    certificate = binding.certificate
    if (
        profile.execution_family != HOSTED_TEXT_EXECUTION_FAMILY
        or binding.status.profile_id != profile.profile_id
        or binding.status.profile_revision != profile.revision
        or binding.status.status != "available"
        or certificate.certificate_kind != "hosted_text_capability"
        or certificate.profile_id != profile.profile_id
        or certificate.profile_revision != profile.revision
        or certificate.profile_digest != canonical_digest(profile)
        or certificate.workspace_tools
        or certificate.action_loop
        or certificate.workspace_actions
        or binding.provider_routing_digest
        != canonical_digest(binding.provider_routing_snapshot)
    ):
        raise ValueError("Hosted text execution binding identity is invalid.")
    expected_digest = canonical_digest(replace(binding, binding_digest=""))
    if binding.binding_digest != expected_digest:
        raise ValueError("Hosted text execution binding digest is invalid.")


def _provider_routing_snapshot(
    store,
    *,
    workspace_id: str,
    provider_id: str,
    model_id: str,
) -> dict[str, object]:
    if provider_id != "openrouter":
        return {}
    getter = getattr(store, "get_hosted_provider_selection", None)
    selection = (
        getter(workspace_id=workspace_id, profile="fast_model")
        if callable(getter)
        else None
    )
    routing = (
        None
        if selection is None
        else selection.openrouter_provider_routing_by_model.get(model_id)
    )
    return _json_snapshot(routing)


def _json_snapshot(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return json.loads(
        json.dumps(dict(value), ensure_ascii=True, sort_keys=True, allow_nan=False)
    )


def _model_limit(model: ProviderModelOption, *keys: str) -> int | None:
    values = [model.metadata.get(key) for key in keys]
    values.extend(
        item.get(key)
        for item in model.upstream_provider_options
        for key in keys
    )
    positive = [
        int(value)
        for value in values
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    return min(positive) if positive else None


def _first_network_host(definition: ProviderDefinition) -> str:
    for requirement in definition.network_requirements:
        if requirement.allowed_hosts:
            return requirement.allowed_hosts[0]
    return ""


def _retention_policy(definition: ProviderDefinition) -> str:
    return str(definition.cost_metadata.get("retention_policy") or "provider_contract")


def _data_destination(definition: ProviderDefinition) -> str:
    host = _first_network_host(definition)
    return f"{definition.label} · {host}" if host else definition.label


__all__ = [
    "HostedTextCapabilityCertificate",
    "HostedTextExecutionBinding",
    "HostedTextProfileDefinition",
    "HostedTextProfileStatus",
    "build_hosted_text_profile",
    "fork_hosted_text_execution_binding",
    "hosted_text_binding_from_document",
    "pin_hosted_text_execution_binding",
    "validate_hosted_text_execution_binding",
]
