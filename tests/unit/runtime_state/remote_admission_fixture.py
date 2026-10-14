"""Domain fixtures extracted without changing assertions."""

from __future__ import annotations
from datetime import datetime
from types import SimpleNamespace
from core.providers.agentic_models import codex_routing_constraint, codex_runtime_capabilities, codex_runtime_policy
from core.runtime.execution_binding import build_runtime_execution_binding
from core.runtime.agentic_feature_flags import LOOPINO_FEATURE_GOOGLE_AGENTIC_PREVIEW, LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME, LOOPINO_FEATURE_OPENROUTER_AGENTIC_PREVIEW
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection

def _identity(provider_id: str):
    return SimpleNamespace(
        runtime_engine_id="hosted-agent-runtime",
        adapter_id="hosted-agent-adapter",
        model_provider_id=provider_id,
        provider_protocol=f"{provider_id}-agentic-v1",
    )


def _remote_binding(*, provider_id: str, now: datetime):
    return build_runtime_execution_binding(
        session_id=f"session-{provider_id}",
        workspace_id="workspace-1",
        workspace_binding_id=f"binding-{provider_id}",
        runtime_engine_id="loopino-tool-loop",
        adapter_id="loopino-hosted-tool-loop",
        adapter_version="candidate",
        model_provider_id=provider_id,
        model_id="fixture-model",
        model_revision="fixture-revision",
        model_revision_policy="exact",
        provider_protocol=f"{provider_id}-agentic-v1",
        provider_api_version="v1",
        routing_constraint=codex_routing_constraint(),
        credential_binding_id="credential-fixture",
        reasoning_effort="high",
        reasoning_efforts=("high",),
        capabilities=codex_runtime_capabilities(),
        execution_mode="sandbox",
        runtime_policy=codex_runtime_policy(),
        egress_policy_id="fixture-egress",
        egress_policy_revision="1",
        created_at=now,
    )


def _runtime_store() -> RuntimeDocumentStore:
    return RuntimeDocumentStore(
        RuntimeCollections(
            sessions=FakeCollection(),
            turns=FakeCollection(),
            events=FakeCollection(),
            processes=FakeCollection(),
            states=FakeCollection(),
            threads=FakeCollection(),
            provider_states=FakeCollection(),
        )
    )


class _AttestationStore:
    def __init__(self, *records) -> None:
        self.records = list(records)
        self.calls = 0

    def get_data_attestation(self, workspace_id: str):
        self.calls += 1
        if not self.records:
            return None
        record = self.records[min(self.calls - 1, len(self.records) - 1)]
        if record is not None and record.workspace_id != workspace_id:
            return record
        return record


def _remote_environment(provider_id: str) -> dict[str, str]:
    return {
        LOOPINO_FEATURE_HOSTED_AGENT_RUNTIME: "1",
        (
            LOOPINO_FEATURE_GOOGLE_AGENTIC_PREVIEW
            if provider_id == "google-ai-studio"
            else LOOPINO_FEATURE_OPENROUTER_AGENTIC_PREVIEW
        ): "1",
    }
