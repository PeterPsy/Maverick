"""Executable result-policy gate for the hosted Full Workspace contract."""

from __future__ import annotations

from types import SimpleNamespace

from core.runtime.hosted_filesystem_result_behavior import (
    FILESYSTEM_RESULT_BEHAVIOR_IDS,
    inspect_hosted_filesystem_result_behavior,
)
from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult


HOSTED_TOOL_RESULT_BEHAVIOR_REVISION = 2
HOSTED_REQUIRED_RESULT_BEHAVIOR_HANDLES = (
    *FILESYSTEM_RESULT_BEHAVIOR_IDS,
    "core-capability:shell.run",
    "core-capability:process.status",
    "core-capability:cli.list",
    "core-capability:cli.run",
    "core-capability:mcp.list",
    "core-capability:mcp.call",
)


class _Definitions:
    def __init__(self, values):
        self.values = values

    def get_command(self, identity):
        return self.values[identity]

    def get_tool(self, identity):
        return self.values[identity]


class _Processes:
    def has_pending_workspace_effects(self, *, process_id, **_context):
        return process_id == "mutating-process"


def inspect_hosted_tool_result_behavior() -> tuple[str, ...]:
    """Exercise concrete classification, pairing, and pre-effect policy behavior."""
    definitions = {
        "fixture.read": SimpleNamespace(effect_class="read"),
        "fixture.mutate": SimpleNamespace(effect_class="mutating"),
    }
    registry = _Definitions(definitions)
    admission = build_hosted_tool_result_admission_resolver(
        cli_registry=registry,
        mcp_registry=registry,
    )
    preflight = build_hosted_tool_result_preflight_resolver(
        cli_registry=registry,
        mcp_registry=registry,
        process_registry=_Processes(),
    )
    context = RuntimeToolActorContext(
        workspace_id="behavior-probe",
        actor_id="core",
        agent_id="behavior-probe",
        platform_role="admin",
        workspace_role="owner",
        session_id="behavior-probe",
        execution_mode="full-access",
    )
    public_payload = {"output": "behavior probe", "complete": True}
    sensitive_payload = {"output": "customer SSN 123-45-6789"}
    scenarios = {
        "core-capability:shell.run": (
            {"mutation_scopes": []},
            {"mutation_scopes": [{"path": "."}]},
        ),
        "core-capability:process.status": (
            {"process_id": "read-process"},
            {"process_id": "mutating-process"},
        ),
        "core-capability:cli.list": ({},),
        "core-capability:cli.run": (
            {"command_id": "fixture.read"},
            {"command_id": "fixture.mutate"},
        ),
        "core-capability:mcp.list": ({},),
        "core-capability:mcp.call": (
            {"tool_name": "fixture.read"},
            {"tool_name": "fixture.mutate"},
        ),
    }
    variable_results = tuple(
        handle
        for handle, scenario_arguments in scenarios.items()
        if all(
            _scenario_complete(
                handle,
                arguments,
                public_payload=public_payload,
                sensitive_payload=sensitive_payload,
                context=context,
                admission=admission,
                preflight=preflight,
            )
            for arguments in scenario_arguments
        )
    )
    return (*inspect_hosted_filesystem_result_behavior(), *variable_results)


def _scenario_complete(
    handle,
    arguments,
    *,
    public_payload,
    sensitive_payload,
    context,
    admission,
    preflight,
) -> bool:
    decision = preflight(handle, arguments, context)
    if decision is None or not decision.admitted_before_effect:
        return False
    public = admission(handle, arguments, public_payload, context)
    sensitive = admission(handle, arguments, sensitive_payload, context)
    if (
        not isinstance(public, RuntimeToolSurfaceResult)
        or public.payload != public_payload
        or public.classification.data_class != "public"
        or not isinstance(sensitive, RuntimeToolSurfaceResult)
        or sensitive.classification.data_class != "regulated_or_customer_data"
    ):
        return False
    paired_public = pairing_safe_tool_result(
        public.payload,
        is_error=False,
        result_data_class=public.classification.data_class,
        allowed_remote_data_classes=("public",),
    )
    paired_sensitive = pairing_safe_tool_result(
        sensitive.payload,
        is_error=False,
        result_data_class=sensitive.classification.data_class,
        allowed_remote_data_classes=("public",),
    )
    return paired_public == (public_payload, False) and paired_sensitive == (
        {"error": "tool_result_egress_denied"},
        True,
    )


__all__ = [
    "HOSTED_REQUIRED_RESULT_BEHAVIOR_HANDLES",
    "HOSTED_TOOL_RESULT_BEHAVIOR_REVISION",
    "inspect_hosted_tool_result_behavior",
]
