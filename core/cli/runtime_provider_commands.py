"""Runtime and provider core CLI commands."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from core.cli.core_command_helpers import OPERATOR_ONLY, WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.providers.payloads import (
    hosted_provider_selection_payload,
    provider_payload,
    routing_decision_payload,
    sort_provider_definitions,
)
from core.providers.agentic_containment import run_remote_agentic_containment
from core.providers.provider_registry import ProviderRegistry
from core.providers.routing import ProviderRoutingContext, select_provider_for_profile
from core.providers.service import activate_hosted_model_provider, effective_provider_registry, is_retired_provider_definition
from core.providers.store import ProviderStore
from core.runtime.runtime_session import runtime_session_allows_user_thread
from core.runtime.store import RuntimeStore
from core.secrets.store import SecretStore


def runtime_provider_command_specs(
    *,
    provider_store: ProviderStore | None = None,
    runtime_store: RuntimeStore | None = None,
    provider_registry: ProviderRegistry | None = None,
    secret_store: SecretStore | None = None,
    observability_store=None,
) -> list[tuple[CliCommandDefinition, Any]]:
    """Build runtime and provider command specs."""
    def _runtime_status_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if runtime_store is None or context.workspace_id is None:
            return {"workspace_id": context.workspace_id, "sessions": []}
        return {
            "command_id": "core.runtime.status",
            "workspace_id": context.workspace_id,
            "sessions": [
                {
                    "session_id": item.session_id,
                    "agent_id": item.agent_id,
                    "status": item.status,
                    "effective_mode": item.effective_mode,
                    "runtime_mode": item.runtime_mode,
                }
                for item in runtime_store.list_sessions(context.workspace_id)
                if runtime_session_allows_user_thread(item)
            ],
        }

    def _providers_list_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        definitions = _provider_definitions(provider_store, provider_registry)
        if not definitions:
            return {"providers": []}
        return {
            "command_id": "core.providers.list",
            "providers": [provider_payload(item) for item in definitions],
        }

    def _providers_route_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"command_id": "core.providers.route", "error": "provider_store_unavailable"}
        workspace_id = str(arguments.get("workspace_id") or context.workspace_id or "").strip()
        if not workspace_id:
            return {"command_id": "core.providers.route", "error": "workspace_id_required"}
        decision = select_provider_for_profile(
            str(arguments.get("profile") or "fast_model"),
            ProviderRoutingContext(
                workspace_id=workspace_id,
                provider_store=provider_store,
                registry=effective_provider_registry(provider_store, registry=provider_registry),
                secret_store=secret_store,
                request_id=str(arguments.get("request_id") or "").strip() or None,
                user_tier=str(arguments.get("user_tier") or "").strip() or None,
                app_id=str(arguments.get("app_id") or "").strip() or None,
                allow_fallback_codex=bool(arguments.get("allow_fallback_codex")),
            ),
        )
        return {"command_id": "core.providers.route", "decision": routing_decision_payload(decision)}

    def _providers_hosted_activate_handler(arguments: dict[str, Any], context: CliInvocationContext) -> dict[str, Any]:
        if provider_store is None:
            return {"command_id": "core.providers.hosted.activate", "error": "provider_store_unavailable"}
        if secret_store is None:
            return {"command_id": "core.providers.hosted.activate", "error": "secret_store_unavailable"}
        workspace_id = str(arguments.get("workspace_id") or context.workspace_id or "").strip()
        provider_id = str(arguments.get("provider_id") or "").strip()
        secret_ref = str(arguments.get("secret_ref") or "").strip()
        if not workspace_id:
            return {"command_id": "core.providers.hosted.activate", "error": "workspace_id_required"}
        if not provider_id:
            return {"command_id": "core.providers.hosted.activate", "error": "provider_id_required"}
        if not secret_ref:
            return {"command_id": "core.providers.hosted.activate", "error": "secret_ref_required"}
        try:
            activation = activate_hosted_model_provider(
                provider_store,
                secret_store=secret_store,
                workspace_id=workspace_id,
                provider_id=provider_id,
                secret_ref=secret_ref,
                label=str(arguments.get("label") or "").strip() or None,
                observability_store=observability_store,
            )
        except Exception as error:
            return {
                "command_id": "core.providers.hosted.activate",
                "error": "hosted_provider_activation_failed",
                "error_type": type(error).__name__,
            }
        return {
            "command_id": "core.providers.hosted.activate",
            "workspace_id": workspace_id,
            "provider": provider_payload(activation.definition),
            "credential_binding": _provider_credential_binding_payload(activation.credential_binding),
            "hosted_selection": hosted_provider_selection_payload(activation.hosted_selection),
            "preflight": routing_decision_payload(activation.routing_decision),
        }

    def _remote_agentic_containment_dry_run_handler(
        arguments: dict[str, Any],
        context: CliInvocationContext,
    ) -> dict[str, Any]:
        if provider_store is None or runtime_store is None:
            return {
                "command_id": "core.providers.agentic.containment.dry-run",
                "error": "containment_store_unavailable",
            }
        return {
            "command_id": "core.providers.agentic.containment.dry-run",
            "report": asdict(
                run_remote_agentic_containment(
                    provider_store,
                    runtime_store,
                    mode="dry_run",
                )
            ),
        }

    def _remote_agentic_containment_apply_handler(
        arguments: dict[str, Any],
        context: CliInvocationContext,
    ) -> dict[str, Any]:
        command_id = "core.providers.agentic.containment.apply"
        if provider_store is None or runtime_store is None:
            return {"command_id": command_id, "error": "containment_store_unavailable"}
        if str(arguments.get("confirmation") or "") != "phase-0-reviewed":
            return {
                "command_id": command_id,
                "error": "containment_apply_confirmation_required",
                "required_confirmation": "phase-0-reviewed",
            }
        plan_digest = str(arguments.get("plan_digest") or "").strip()
        try:
            report = run_remote_agentic_containment(
                provider_store,
                runtime_store,
                mode="apply",
                expected_plan_digest=plan_digest,
                observability_store=observability_store,
            )
        except ValueError as error:
            return {"command_id": command_id, "error": str(error)}
        return {"command_id": command_id, "report": asdict(report)}

    return [
        (
            core_cli_command(
                command_id="core.runtime.status",
                path_segments=["core", "runtime", "status"],
                description="Inspect runtime status for the active workspace.",
                owner_id="runtime",
                invocation_policy=OPERATOR_ONLY,
            ),
            _runtime_status_handler,
        ),
        (
            core_cli_command(
                command_id="core.providers.list",
                path_segments=["core", "providers", "list"],
                description="Inspect configured provider definitions.",
                owner_id="providers",
                invocation_policy=WORKSPACE_SAFE,
            ),
            _providers_list_handler,
        ),
        (
            core_cli_command(
                command_id="core.providers.route",
                path_segments=["core", "providers", "route"],
                description="Simulate a read-only provider routing decision.",
                owner_id="providers",
                invocation_policy=WORKSPACE_SAFE,
                argument_schema={
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "profile": {"type": "string"},
                        "request_id": {"type": "string"},
                        "user_tier": {"type": "string"},
                        "app_id": {"type": "string"},
                        "allow_fallback_codex": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            ),
            _providers_route_handler,
        ),
        (
            core_cli_command(
                command_id="core.providers.hosted.activate",
                path_segments=["core", "providers", "hosted", "activate"],
                description="Operator activation for a hosted text model provider.",
                owner_id="providers",
                invocation_policy=OPERATOR_ONLY,
                argument_schema={
                    "type": "object",
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "provider_id": {"type": "string"},
                        "secret_ref": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["provider_id", "secret_ref"],
                    "additionalProperties": False,
                },
            ),
            _providers_hosted_activate_handler,
        ),
        (
            replace(
                core_cli_command(
                    command_id="core.providers.agentic.containment.dry-run",
                    path_segments=["core", "providers", "agentic", "containment", "dry-run"],
                    description="Inventory and plan Phase-0 remote agentic containment without mutation.",
                    owner_id="providers",
                    invocation_policy=OPERATOR_ONLY,
                    argument_schema={"type": "object", "additionalProperties": False},
                ),
                effect_class="read",
                safe_to_retry=True,
            ),
            _remote_agentic_containment_dry_run_handler,
        ),
        (
            replace(
                core_cli_command(
                    command_id="core.providers.agentic.containment.apply",
                    path_segments=["core", "providers", "agentic", "containment", "apply"],
                    description="Apply a reviewed Phase-0 remote agentic containment plan through CAS stores.",
                    owner_id="providers",
                    invocation_policy=OPERATOR_ONLY,
                    argument_schema={
                        "type": "object",
                        "properties": {
                            "confirmation": {"type": "string", "enum": ["phase-0-reviewed"]},
                            "plan_digest": {
                                "type": "string",
                                "minLength": 64,
                                "maxLength": 64,
                            },
                        },
                        "required": ["confirmation", "plan_digest"],
                        "additionalProperties": False,
                    },
                ),
                effect_class="mutating",
                supports_idempotency=True,
                safe_to_retry=True,
            ),
            _remote_agentic_containment_apply_handler,
        ),
    ]


def _provider_credential_binding_payload(binding) -> dict[str, object] | None:
    if binding is None:
        return None
    return {
        "binding_id": binding.binding_id,
        "provider_id": binding.provider_id,
        "workspace_id": binding.workspace_id,
        "label": binding.label,
        "status": binding.status,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def _provider_definitions(
    provider_store: ProviderStore | None,
    provider_registry: ProviderRegistry | None,
) -> list:
    if provider_store is not None:
        registry = effective_provider_registry(provider_store, registry=provider_registry)
        return sort_provider_definitions([
            definition
            for definition in registry.list_provider_definitions()
            if not is_retired_provider_definition(definition)
        ])
    if provider_registry is not None:
        return sort_provider_definitions([
            definition
            for definition in provider_registry.list_provider_definitions()
            if not is_retired_provider_definition(definition)
        ])
    return []
