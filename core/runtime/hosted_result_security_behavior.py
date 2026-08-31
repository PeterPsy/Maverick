"""Executable negative security probes for the hosted result contract."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import hashlib
from types import SimpleNamespace

from core.egress.classification import fail_closed_classification
from core.runtime.classification_authority import (
    revalidate_canonical_classification,
)
from core.runtime.confined_filesystem import FilesystemResourceObservation
from core.runtime.content_data_classification import (
    narrow_runtime_content_classification,
)
from core.runtime.filesystem_mutation_lineage import (
    resolve_filesystem_mutation_lineage,
)
from core.runtime.hosted_agentic_tool_results import pairing_safe_tool_result
from core.runtime.public_content_authority_store import (
    issue_runtime_public_content_authority,
    revoke_runtime_public_content_authority,
)
from core.runtime.public_content_classification import (
    classification_from_runtime_public_content_authority,
)
from core.runtime.tool_private_payloads import canonical_tool_arguments
from core.shared.in_memory_collection import InMemoryCollection
from core.workspaces.store import WorkspaceCollections, WorkspaceDocumentStore


HOSTED_RESULT_SECURITY_BEHAVIOR_IDS = (
    "security:filesystem.marker-narrowing",
    "security:filesystem.revoke-rebuild",
    "security:tool-result.revoke-egress",
)
_PROBE_TIME = datetime(2026, 8, 31, tzinfo=UTC)


@lru_cache(maxsize=1)
def inspect_hosted_result_security_behavior() -> tuple[str, ...]:
    """Run marker, reconstructed-lineage, and delayed-egress denials."""
    try:
        return _inspect()
    except Exception:
        return ()


def _inspect() -> tuple[str, ...]:
    store = _workspace_store()
    workspace_id = "hosted-result-security-probe"
    issued = issue_runtime_public_content_authority(
        store,
        workspace_id=workspace_id,
        actor_id="core-security-probe",
        expected_revision=0,
        now=_PROBE_TIME,
    )
    source_digest = "a" * 64
    classification = classification_from_runtime_public_content_authority(
        issued,
        workspace_id=workspace_id,
        provenance="tool_result",
        trust_level="untrusted_tool_output",
        source_ref="security-probe.txt",
        source_revision=source_digest,
        source_digest=source_digest,
        resource_identity="security-probe:1",
    )
    verified: set[str] = set()

    sensitive_payloads = (
        {"content": "customer SSN 123-45-6789\n"},
        {
            "instructions": [
                {"content": "instruction SSN 123-45-6789\n"}
            ]
        },
        {
            "matches": [
                {"text": "search result SSN 123-45-6789"}
            ]
        },
    )
    marker_results = []
    for payload in sensitive_payloads:
        narrowed = narrow_runtime_content_classification(
            classification,
            payload,
            content_type="application/json",
        )
        marker_results.append(
            (
                narrowed,
                pairing_safe_tool_result(
                    payload,
                    is_error=False,
                    result_data_class=narrowed.data_class,
                    allowed_remote_data_classes=("public",),
                ),
            )
        )
    if all(
        narrowed.data_class == "regulated_or_customer_data"
        and narrowed.classification_authority_id == issued.classification_id
        and paired == ({"error": "tool_result_egress_denied"}, True)
        for narrowed, paired in marker_results
    ):
        verified.add("security:filesystem.marker-narrowing")

    observation = FilesystemResourceObservation(
        workspace_id=workspace_id,
        resource_kind="filesystem_file",
        resource_ref="security-probe.txt",
        resource_identity="security-probe:2",
        resource_revision="b" * 64,
        resource_digest="b" * 64,
    )
    mutation_payload = {
        "path": observation.resource_ref,
        "resource_identity": observation.resource_identity,
        "resource_revision": observation.resource_revision,
        "resource_digest": observation.resource_digest,
    }
    result_digest = hashlib.sha256(
        canonical_tool_arguments(mutation_payload)
    ).hexdigest()
    mutation_record = SimpleNamespace(
        invocation_id="security-probe-mutation",
        workspace_id=workspace_id,
        session_id="security-probe-session",
        state="succeeded",
        resolved_tool_handle="core-capability:filesystem.write",
        result_data_class=classification.data_class,
        result_trust_level=classification.trust_level,
        result_provenance="tool_result",
        result_classification_revision=classification.classification_revision,
        result_classification_authority_id=(
            classification.classification_authority_id
        ),
        result_classification_authority_kind=(
            classification.classification_authority_kind
        ),
        result_classification_authority_ref=(
            classification.classification_authority_ref
        ),
        result_classification_authority_revision=(
            classification.classification_authority_revision
        ),
        result_classification_authority_digest=(
            classification.classification_authority_digest
        ),
        result_classification_authority_policy_revision=(
            classification.classification_authority_policy_revision
        ),
        result_classification_authority_bound=(
            classification.classification_authority_bound
        ),
        result_source_revision=result_digest,
        result_source_digest=result_digest,
        result_artifact_private_ref=None,
    )
    ledger = _ProbeLedger(mutation_record, mutation_payload)
    authoritative = fail_closed_classification(
        provenance="tool_result",
        source_ref=observation.resource_ref,
        source_revision=observation.resource_revision,
        source_digest=observation.resource_digest,
        resource_identity=observation.resource_identity,
    )
    before_revoke = resolve_filesystem_mutation_lineage(
        observation=observation,
        provenance="tool_result",
        authoritative=authoritative,
        ledger=ledger,
        session_id=mutation_record.session_id,
        authority_store=store,
    )
    revoke_runtime_public_content_authority(
        store,
        workspace_id=workspace_id,
        actor_id="core-security-probe",
        expected_revision=issued.revision,
        reason="hosted result contract negative probe",
        now=_PROBE_TIME,
    )
    after_revoke = resolve_filesystem_mutation_lineage(
        observation=observation,
        provenance="tool_result",
        authoritative=authoritative,
        ledger=_ProbeLedger(
            SimpleNamespace(**vars(mutation_record)),
            mutation_payload,
        ),
        session_id=mutation_record.session_id,
        authority_store=store,
    )
    if (
        before_revoke.data_class == "public"
        and after_revoke.data_class == "unclassified"
        and after_revoke.classification_revision is None
    ):
        verified.add("security:filesystem.revoke-rebuild")

    delayed_payload = {"output": "REVOCATION_PRIVATE_MARKER"}
    revalidated = revalidate_canonical_classification(
        store,
        workspace_id=workspace_id,
        classification=classification,
    )
    paired_delayed = pairing_safe_tool_result(
        delayed_payload,
        is_error=False,
        result_data_class=revalidated.data_class,
        allowed_remote_data_classes=("public",),
    )
    if (
        revalidated.data_class == "unclassified"
        and paired_delayed == ({"error": "tool_result_egress_denied"}, True)
        and "REVOCATION_PRIVATE_MARKER" not in repr(paired_delayed)
    ):
        verified.add("security:tool-result.revoke-egress")

    return tuple(
        behavior
        for behavior in HOSTED_RESULT_SECURITY_BEHAVIOR_IDS
        if behavior in verified
    )


def _workspace_store() -> WorkspaceDocumentStore:
    return WorkspaceDocumentStore(
        WorkspaceCollections(
            workspaces=InMemoryCollection(),
            memberships=InMemoryCollection(),
            governance=InMemoryCollection(),
            quotas=InMemoryCollection(),
            active_workspace_selections=InMemoryCollection(),
            data_attestations=InMemoryCollection(),
            resource_classifications=InMemoryCollection(),
            data_governance_audits=InMemoryCollection(),
        )
    )


class _ProbeLedger:
    def __init__(self, record, result) -> None:
        self._record = record
        self._result = dict(result)
        self.store = SimpleNamespace(
            list_tool_invocations=self._list_tool_invocations
        )

    def _list_tool_invocations(self, *, session_id):
        return [self._record] if session_id == self._record.session_id else []

    def load_result(self, record):
        if record.invocation_id != self._record.invocation_id:
            raise KeyError(record.invocation_id)
        return dict(self._result)


__all__ = [
    "HOSTED_RESULT_SECURITY_BEHAVIOR_IDS",
    "inspect_hosted_result_security_behavior",
]
