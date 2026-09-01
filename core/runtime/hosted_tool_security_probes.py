"""Production-composed negative probes for hosted tool security boundaries."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
import tempfile

from core.cli.command_registry import CliCommandRegistry
from core.mcp.tool_registry import McpToolRegistry
from core.providers.capability_models import RuntimeCapabilitySet
from core.runtime.authority import EffectiveRuntimeAuthority
from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result
from core.runtime.public_content_classification import (
    classification_from_runtime_public_content_authority,
)
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from core.runtime.tool_catalog import RuntimeToolActorContext, RuntimeToolCatalogBuilder
from core.runtime.tool_core_capabilities import build_core_runtime_tool_capabilities
from core.runtime.tool_ledger import RuntimeToolLedger
from core.runtime.tool_orchestrator import (
    RuntimeToolConfirmationPolicy,
    RuntimeToolOrchestrator,
)
from core.runtime.tool_private_payloads import (
    InMemoryRuntimeToolPrivatePayloadStore,
)
from core.runtime.tool_schema import provider_tool_name
from core.shared.in_memory_collection import InMemoryCollection


_PROBE_TIME = datetime(2026, 9, 1, tzinfo=UTC)


def probe_production_filesystem_marker_narrowing(
    authority_store,
    public_authority,
) -> bool:
    """Read raw sensitive bytes through the ledgered production orchestrator."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        workspace_id = public_authority.workspace_id
        marker = b"customer SSN 123-45-6789 suffix\n"
        (root / "customer.txt").write_bytes(marker)

        def classify(observation, provenance):
            return classification_from_runtime_public_content_authority(
                public_authority,
                workspace_id=observation.workspace_id,
                provenance=provenance,
                trust_level="untrusted_tool_output",
                source_ref=observation.resource_ref,
                source_revision=observation.resource_revision,
                source_digest=observation.resource_digest,
                resource_identity=observation.resource_identity,
            )

        ledger = RuntimeToolLedger(
            store=_runtime_store(),
            private_payload_store=InMemoryRuntimeToolPrivatePayloadStore(),
            digest_key=b"hosted-tool-security-probe-key!!",
        )
        capabilities = build_core_runtime_tool_capabilities(
            workspace_id=workspace_id,
            workspace_root=root,
            resource_classification_resolver=classify,
        )
        orchestrator = RuntimeToolOrchestrator(
            catalog_builder=RuntimeToolCatalogBuilder(
                cli_registry=CliCommandRegistry(),
                mcp_registry=McpToolRegistry(),
                core_capabilities=capabilities,
            ),
            ledger=ledger,
            classification_authority_store=authority_store,
        )
        context = _actor_context(workspace_id)
        runtime_authority = _filesystem_read_authority()
        policy = RuntimeToolConfirmationPolicy(
            policy_revision="security-probe:filesystem:1",
            require_confirmation_for_mutating=False,
            require_confirmation_for_destructive=False,
            max_tool_result_bytes=262_144,
        )
        split_at = len(b"customer SSN 123-4")
        base64_result = _invoke_read(
            orchestrator,
            runtime_authority,
            context,
            policy,
            call_id="marker-base64",
            arguments={"path": "customer.txt", "encoding": "base64"},
        )
        first = _invoke_read(
            orchestrator,
            runtime_authority,
            context,
            policy,
            call_id="marker-chunk-1",
            arguments={"path": "customer.txt", "max_bytes": split_at},
        )
        first_payload = ledger.load_result(first.invocation)
        second = _invoke_read(
            orchestrator,
            runtime_authority,
            context,
            policy,
            call_id="marker-chunk-2",
            arguments={
                "path": "customer.txt",
                "offset": first_payload["next_offset"],
                "expected_resource_identity": first_payload[
                    "resource_identity"
                ],
                "expected_resource_revision": first_payload[
                    "resource_revision"
                ],
            },
        )
        base64_payload = ledger.load_result(base64_result.invocation)
        second_payload = ledger.load_result(second.invocation)
        reconstructed = (
            str(first_payload["content"]) + str(second_payload["content"])
        ).encode("utf-8")
        raw_projection = base64.b64decode(
            str(base64_payload["content_base64"]),
            validate=True,
        )
        outcomes = (base64_result, first, second)
        return bool(
            raw_projection == marker
            and reconstructed == marker
            and all(
                outcome.invocation.state == "succeeded"
                and outcome.invocation.result_data_class
                == "regulated_or_customer_data"
                and outcome.invocation.result_classification_authority_id
                == public_authority.classification_id
                and pairing_safe_tool_result(
                    ledger.load_result(outcome.invocation),
                    is_error=False,
                    result_data_class=(
                        orchestrator.persisted_result_classification(
                            outcome.invocation
                        ).data_class
                    ),
                    allowed_remote_data_classes=("public",),
                )
                == ({"error": "tool_result_egress_denied"}, True)
                for outcome in outcomes
            )
        )


def _invoke_read(
    orchestrator,
    authority,
    context,
    policy,
    *,
    call_id: str,
    arguments: dict[str, object],
):
    return orchestrator.invoke_provider_tool(
        provider_tool_name=provider_tool_name(
            "core-capability:filesystem.read"
        ),
        provider_tool_call_id=call_id,
        arguments=arguments,
        authority=authority,
        context=context,
        turn_id="security-probe-turn",
        policy=policy,
    )


def _actor_context(workspace_id: str) -> RuntimeToolActorContext:
    return RuntimeToolActorContext(
        workspace_id=workspace_id,
        actor_id="core-security-probe",
        agent_id="core-security-probe",
        platform_role="admin",
        workspace_role="owner",
        session_id="security-probe-session",
        execution_mode="full-access",
    )


def _filesystem_read_authority() -> EffectiveRuntimeAuthority:
    return EffectiveRuntimeAuthority(
        execution_binding_id="security-probe-binding",
        turn_id="security-probe-turn",
        certificate_id="security-probe-certificate",
        allowed_capabilities=RuntimeCapabilitySet(
            streaming=True,
            tool_orchestration=True,
            cli=False,
            mcp=False,
            skill_catalog=False,
            filesystem_list=False,
            filesystem_read=True,
            filesystem_write=False,
            shell=False,
            interrupt=True,
            same_turn_steering=False,
            recovery=True,
            confirmation_resume=True,
            provider_private_state=False,
            attachment_modalities=(),
        ),
        allowed_tool_handles=("core-capability:filesystem.read",),
        execution_mode="full-access",
        egress_policy_id="security-probe-public",
        policy_revision_set=("security-probe:1",),
        health_revision="security-probe-health:1",
        authority_digest="security-probe-authority",
        computed_at=_PROBE_TIME,
        allowed_remote_data_classes=("public",),
    )


def _runtime_store() -> RuntimeDocumentStore:
    collection = InMemoryCollection
    return RuntimeDocumentStore(
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


__all__ = [
    "probe_production_filesystem_marker_narrowing",
]
