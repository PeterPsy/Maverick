"""Production-composed hosted CLI/MCP collaboration behavior probe."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
import tempfile

from core.cli.command_registry import CliCommandRegistry
from core.cli.inter_agent_commands import inter_agent_command_specs
from core.inter_agent.store import build_inter_agent_document_store
from core.mcp.inter_agent_tools import inter_agent_tool_specs
from core.mcp.tool_registry import McpToolRegistry
from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result
from core.runtime.hosted_tool_result_admission import (
    build_hosted_tool_result_admission_resolver,
    build_hosted_tool_result_preflight_resolver,
)
from core.runtime.runtime_session import RuntimeSessionRecord
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolSurfaceResult
from core.runtime.tool_discovery_capabilities import RuntimeToolDiscoveryBroker
from core.shared.in_memory_collection import InMemoryCollection


HOSTED_COLLABORATION_BEHAVIOR_IDS = (
    "core-capability:cli.list",
    "core-capability:cli.run",
    "core-capability:mcp.list",
    "core-capability:mcp.call",
    "collaboration:cli-create-mcp-wait",
)
_WORKSPACE_ID = "behavior-probe"
_SESSION_ID = "collaboration-root"
_PROBE_TIME = datetime(2026, 9, 2, tzinfo=UTC)
_PRIVATE_MARKER = "customer SSN 123-45-6789"


@lru_cache(maxsize=1)
def inspect_hosted_collaboration_behavior() -> tuple[str, ...]:
    """Create via CLI, wait via MCP, and expose only certified projections."""
    try:
        return HOSTED_COLLABORATION_BEHAVIOR_IDS if _probe_workflow() else ()
    except Exception:
        return ()


def _probe_workflow() -> bool:
    with tempfile.TemporaryDirectory() as directory:
        repository_root = Path(directory) / "maverick"
        workspace_root = repository_root / "workspaces" / _WORKSPACE_ID
        runtime_root = workspace_root / "runtime"
        for path in (
            repository_root / "core",
            repository_root / "apps",
            runtime_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        (repository_root / "AGENTS.md").write_text("", encoding="utf-8")
        runtime_store = _runtime_store(workspace_root, runtime_root)
        inter_agent_store = build_inter_agent_document_store(
            start_path=repository_root,
        )
        cli_registry = CliCommandRegistry()
        for definition, handler in inter_agent_command_specs(
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            start_path=repository_root,
        ):
            cli_registry.register_command(definition, handler)
        mcp_registry = McpToolRegistry()
        for definition, handler in inter_agent_tool_specs(
            runtime_store=runtime_store,
            inter_agent_store=inter_agent_store,
            start_path=repository_root,
        ):
            mcp_registry.register_tool(definition, handler)
        admission = build_hosted_tool_result_admission_resolver(
            cli_registry=cli_registry,
            mcp_registry=mcp_registry,
        )
        preflight = build_hosted_tool_result_preflight_resolver(
            cli_registry=cli_registry,
            mcp_registry=mcp_registry,
        )
        broker = RuntimeToolDiscoveryBroker(
            cli_registry=cli_registry,
            mcp_registry=mcp_registry,
            result_classification_resolver=admission,
        )
        context = RuntimeToolActorContext(
            workspace_id=_WORKSPACE_ID,
            actor_id="core-collaboration-probe",
            agent_id="core-collaboration-probe",
            platform_role="admin",
            workspace_role="owner",
            session_id=_SESSION_ID,
            execution_mode="full-access",
        )
        cli_listing = broker.list_cli({}, context, None)
        create_item = next(
            item
            for item in cli_listing.payload["commands"]
            if item["command_id"] == "inter-agent.runs.create"
        )
        create_arguments = {
            "command_id": "inter-agent.runs.create",
            "invocation_token": create_item["invocation_token"],
            "arguments": {
                "thread_id": _SESSION_ID,
                "root_runtime_session_id": _SESSION_ID,
                "mode": "manager_tools",
                "participants": [
                    {
                        "kind": "orchestrator",
                        "execution_mode": "root_orchestrator",
                        "label": _PRIVATE_MARKER,
                    },
                    {
                        "kind": "agent",
                        "execution_mode": "child_runtime_session",
                        "label": "Worker",
                    },
                ],
                "budget": {
                    "max_participants": 2,
                    "max_concurrent_participants": 1,
                    "max_total_turns": 1,
                    "max_turns_per_participant": 1,
                },
            },
        }
        create_decision = preflight(
            "core-capability:cli.run",
            create_arguments,
            context,
        )
        created = broker.run_cli(create_arguments, context, None)
        created = admission(
            "core-capability:cli.run",
            create_arguments,
            created.payload,
            context,
        )
        if not _public_projection(created, "inter-agent.run-create.v1"):
            return False
        run_id = created.payload.get("run_id")
        if not isinstance(run_id, str) or not run_id.startswith("iarun_"):
            return False

        mcp_listing = broker.list_mcp({}, context, None)
        wait_item = next(
            item
            for item in mcp_listing.payload["tools"]
            if item["tool_name"] == "inter_agent_wait"
        )
        wait_arguments = {
            "tool_name": "inter_agent_wait",
            "invocation_token": wait_item["invocation_token"],
            "arguments": {"run_id": run_id, "timeout_seconds": 0},
        }
        wait_decision = preflight(
            "core-capability:mcp.call",
            wait_arguments,
            context,
        )
        waited = broker.call_mcp(wait_arguments, context, None)
        waited = admission(
            "core-capability:mcp.call",
            wait_arguments,
            waited.payload,
            context,
        )
        if not _public_projection(waited, "inter-agent.run-wait.v1"):
            return False
        paired_create = pairing_safe_tool_result(
            created.payload,
            is_error=False,
            result_data_class=created.classification.data_class,
            allowed_remote_data_classes=("public",),
        )
        paired_wait = pairing_safe_tool_result(
            waited.payload,
            is_error=False,
            result_data_class=waited.classification.data_class,
            allowed_remote_data_classes=("public",),
        )
        return bool(
            create_decision.admitted_before_effect
            and create_decision.guaranteed_data_class == "public"
            and wait_decision.admitted_before_effect
            and wait_decision.guaranteed_data_class == "public"
            and create_item["effect_class"] == "mutating"
            and create_item["agentic_result_projection"]
            == "inter-agent.run-create.v1"
            and wait_item["effect_class"] == "read"
            and wait_item["agentic_result_projection"]
            == "inter-agent.run-wait.v1"
            and waited.payload.get("run_id") == run_id
            and _PRIVATE_MARKER not in repr(created.payload)
            and _PRIVATE_MARKER not in repr(waited.payload)
            and paired_create == (created.payload, False)
            and paired_wait == (waited.payload, False)
        )


def _public_projection(result, contract: str) -> bool:
    return bool(
        isinstance(result, RuntimeToolSurfaceResult)
        and result.classification.data_class == "public"
        and result.classification.trust_level == "trusted_platform"
        and result.payload.get("projection_contract") == contract
    )


def _runtime_store(
    workspace_root: Path,
    runtime_root: Path,
) -> RuntimeDocumentStore:
    collection = InMemoryCollection
    store = RuntimeDocumentStore(
        RuntimeCollections(
            sessions=collection(),
            turns=collection(),
            events=collection(),
            processes=collection(),
            states=collection(),
            threads=collection(),
            tool_invocations=collection(),
            tool_confirmation_grants=collection(),
        )
    )
    store.insert_session(
        RuntimeSessionRecord(
            session_id=_SESSION_ID,
            workspace_id=_WORKSPACE_ID,
            agent_id="core-collaboration-probe",
            status="running",
            requested_mode="full-access",
            effective_mode="full-access",
            workspace_root=str(workspace_root),
            workdir=str(workspace_root),
            runtime_root=str(runtime_root),
            started_at=_PROBE_TIME,
            updated_at=_PROBE_TIME,
            ended_at=None,
            last_progress_at=_PROBE_TIME,
            source_app_id="chat",
            owner_user_id="core-collaboration-probe",
        )
    )
    return store


__all__ = [
    "HOSTED_COLLABORATION_BEHAVIOR_IDS",
    "inspect_hosted_collaboration_behavior",
]
