"""Executable result-policy gate for the hosted Full Workspace contract."""

from __future__ import annotations

from types import SimpleNamespace

from core.runtime.hosted_filesystem_result_behavior import (
    FILESYSTEM_RESULT_BEHAVIOR_IDS,
    inspect_hosted_filesystem_result_behavior,
)
from core.runtime.hosted_result_security_behavior import (
    HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
    inspect_hosted_result_security_behavior,
)
from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.public_content_authority import (
    build_runtime_public_content_authority_record,
)
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult
from core.shared.tool_effects import ToolArgumentEffectMap


HOSTED_TOOL_RESULT_BEHAVIOR_REVISION = 5
HOSTED_REQUIRED_RESULT_BEHAVIOR_HANDLES = (
    *FILESYSTEM_RESULT_BEHAVIOR_IDS,
    "core-capability:shell.run",
    "core-capability:process.status",
    "core-capability:cli.list",
    "core-capability:cli.run",
    "core-capability:mcp.list",
    "core-capability:mcp.call",
    *HOSTED_RESULT_SECURITY_BEHAVIOR_IDS,
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
        "fixture.app-mixed": SimpleNamespace(
            effect_class="destructive",
            owner_kind="app",
            schema_public=False,
            certified_tcb_component=None,
            agentic_result_data_class=None,
            argument_effects=ToolArgumentEffectMap(
                argument_name="action",
                omitted_effect_class="read",
                value_effect_classes=(
                    ("catalog", "read"),
                    ("write", "mutating"),
                    ("delete", "destructive"),
                ),
            ),
        ),
    }
    registry = _Definitions(definitions)
    authority = build_runtime_public_content_authority_record(
        workspace_id="behavior-probe",
        actor_id="core-behavior-probe",
        active=True,
    )
    authority_resolver = lambda workspace_id: (
        authority if workspace_id == "behavior-probe" else None
    )
    admission = build_hosted_tool_result_admission_resolver(
        cli_registry=registry,
        mcp_registry=registry,
        public_content_authority_resolver=authority_resolver,
    )
    preflight = build_hosted_tool_result_preflight_resolver(
        cli_registry=registry,
        mcp_registry=registry,
        process_registry=_Processes(),
        public_content_authority_resolver=authority_resolver,
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
            {
                "command_id": "fixture.app-mixed",
                "arguments": {"action": "catalog"},
            },
        ),
        "core-capability:mcp.list": ({},),
        "core-capability:mcp.call": (
            {
                "tool_name": "fixture.app-mixed",
                "arguments": {"action": "catalog"},
            },
        ),
    }
    denied_app_effects = {
        "core-capability:cli.run": (
            {
                "command_id": "fixture.app-mixed",
                "arguments": {"action": "write"},
            },
            {
                "command_id": "fixture.app-mixed",
                "arguments": {"action": "unknown"},
            },
        ),
        "core-capability:mcp.call": (
            {
                "tool_name": "fixture.app-mixed",
                "arguments": {"action": "delete"},
            },
            {
                "tool_name": "fixture.app-mixed",
                "arguments": {"action": "unknown"},
            },
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
        and all(
            not preflight(handle, arguments, context).admitted_before_effect
            for arguments in denied_app_effects.get(handle, ())
        )
    )
    return (
        *inspect_hosted_filesystem_result_behavior(),
        *variable_results,
        *inspect_hosted_result_security_behavior(),
    )


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
