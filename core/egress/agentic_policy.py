"""Fail-closed per-block egress evaluation for hosted agentic requests."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import hmac
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from core.egress.agentic_models import (
    AgenticEgressContentBlock,
    AgenticEgressDecision,
    AgenticEgressDecisionStore,
    AgenticEgressPolicy,
    AgenticEgressResult,
)
from core.egress.agentic_transforms import (
    canonical_egress_content,
    transform_exportable_content,
)
from core.observability.service import record_platform_audit
from core.observability.store import ObservabilityStore

if TYPE_CHECKING:
    from core.workspaces.data_governance import WorkspaceDataAttestation


MAX_EGRESS_BLOCK_BYTES = 1_048_576
_DIGEST_DOMAIN = b"maverick.agentic-egress.content.v1\x00"
_KNOWN_DATA_CLASSES = {
    "public",
    "workspace_internal_fake",
    "workspace_internal",
    "personal_data",
    "credential_or_secret",
    "regulated_or_customer_data",
    "host_operational_metadata",
    "unclassified",
}
_KNOWN_PROVENANCE = {
    "platform_instruction",
    "runtime_context",
    "runtime_capabilities",
    "workspace_instruction",
    "agent_instruction",
    "skill_fragment",
    "finalization_instruction",
    "prompt",
    "user_input",
    "orchestration_context",
    "governed_context",
    "skill",
    "attachment",
    "app_reference",
    "tool_schema",
    "tool_result",
    "provider_state",
}
_KNOWN_TRUST = {
    "trusted_platform",
    "trusted_actor",
    "untrusted_external",
    "untrusted_tool_output",
}
_ALWAYS_DENIED_DATA_CLASSES = {
    "credential_or_secret",
    "host_operational_metadata",
    "unclassified",
}


class AgenticEgressEvaluator:
    """Evaluate classified content and persist only HMAC-based audit metadata."""

    def __init__(
        self,
        *,
        digest_key: bytes,
        observability_store: ObservabilityStore | None = None,
        decision_store: AgenticEgressDecisionStore | None = None,
    ) -> None:
        if len(digest_key) < 32:
            raise ValueError("Agentic egress digest key must contain at least 32 bytes.")
        self._digest_key = bytes(digest_key)
        self.observability_store = observability_store
        self.decision_store = decision_store

    def evaluate(
        self,
        *,
        block: AgenticEgressContentBlock,
        content: object,
        destination_provider_id: str,
        destination_upstream_id: str | None,
        policy: AgenticEgressPolicy,
        data_attestation: WorkspaceDataAttestation | None = None,
        workspace_root: Path | None = None,
        now: datetime | None = None,
        persist: bool = True,
    ) -> AgenticEgressResult:
        """Return transformed bytes, optionally staging the decision for later commit."""
        timestamp = now or datetime.now(tz=UTC)
        source = canonical_egress_content(content)
        source_digest = _content_digest(self._digest_key, source)
        reason = self._deny_reason(
            block=block,
            destination_provider_id=destination_provider_id,
            destination_upstream_id=destination_upstream_id,
            policy=policy,
            source=source,
            data_attestation=data_attestation,
        )
        exported: bytes | None = None
        transformation: str | None = None
        if reason is None:
            exported, transformation, reason = transform_exportable_content(
                source,
                content_type=block.content_type,
                workspace_id=block.workspace_id,
                workspace_root=workspace_root,
                allow_sensitive_transform=policy.transform_sensitive_text,
                allow_host_path_transform=(
                    policy.transform_sensitive_text
                    and block.provenance == "tool_result"
                ),
            )
        allowed = reason is None and exported is not None
        reason_code = "egress_allowed" if allowed else str(reason or "egress_denied")
        attestation_id = (
            data_attestation.attestation_id
            if block.data_class == "workspace_internal_fake"
            and data_attestation is not None
            else None
        )
        attestation_revision = (
            data_attestation.revision
            if block.data_class == "workspace_internal_fake"
            and data_attestation is not None
            else None
        )
        decision_id = str(
            uuid5(
                NAMESPACE_URL,
                ":".join(
                    [
                        "maverick-egress",
                        block.workspace_id,
                        block.session_id,
                        block.turn_id,
                        block.content_block_id,
                        block.data_class,
                        block.provenance,
                        block.trust_level,
                        block.content_type,
                        source_digest,
                        destination_provider_id,
                        destination_upstream_id or "direct",
                        policy.policy_id,
                        policy.revision,
                        str(block.classification_revision or "unverified"),
                        block.classification_authority_id or "no-authority",
                        block.classification_authority_kind or "no-authority-kind",
                        block.classification_authority_ref or "no-authority-ref",
                        str(
                            block.classification_authority_revision
                            or "no-authority-revision"
                        ),
                        (
                            block.classification_authority_digest
                            or "no-authority-digest"
                        ),
                        (
                            block.classification_authority_policy_revision
                            or "no-authority-policy"
                        ),
                        str(block.classification_authority_bound),
                        attestation_id or "no-attestation",
                        str(attestation_revision or "no-revision"),
                        (
                            data_attestation.status
                            if data_attestation is not None
                            else "missing"
                        ),
                    ]
                ),
            )
        )
        decision = AgenticEgressDecision(
            decision_id=decision_id,
            session_id=block.session_id,
            turn_id=block.turn_id,
            content_block_id=block.content_block_id,
            destination_provider_id=destination_provider_id,
            destination_upstream_id=destination_upstream_id,
            data_class=block.data_class,
            provenance=block.provenance,
            trust_level=block.trust_level,
            export_allowed=allowed,
            transformation=transformation,
            source_digest=source_digest,
            exported_digest=(
                _content_digest(self._digest_key, exported) if exported is not None else None
            ),
            policy_id=policy.policy_id,
            policy_revision=policy.revision,
            reason_code=reason_code,
            decided_at=timestamp,
            classification_revision=block.classification_revision,
            attestation_id=attestation_id,
            attestation_revision=attestation_revision,
            classification_authority_id=block.classification_authority_id,
            classification_authority_kind=block.classification_authority_kind,
            classification_authority_ref=block.classification_authority_ref,
            classification_authority_revision=(
                block.classification_authority_revision
            ),
            classification_authority_digest=(
                block.classification_authority_digest
            ),
            classification_authority_policy_revision=(
                block.classification_authority_policy_revision
            ),
            classification_authority_bound=(
                block.classification_authority_bound
            ),
        )
        if persist:
            decision = self.commit_decision(
                workspace_id=block.workspace_id,
                decision=decision,
            )
        return AgenticEgressResult(decision=decision, exported_content=exported)

    def commit_decision(
        self,
        *,
        workspace_id: str,
        decision: AgenticEgressDecision,
    ) -> AgenticEgressDecision:
        """Persist and audit one previously evaluated deterministic decision."""
        if self.decision_store is not None:
            decision = self.decision_store.initialize_egress_decision(
                workspace_id=workspace_id,
                record=decision,
            )
        self._audit(workspace_id, decision)
        return decision

    @staticmethod
    def _deny_reason(
        *,
        block: AgenticEgressContentBlock,
        destination_provider_id: str,
        destination_upstream_id: str | None,
        policy: AgenticEgressPolicy,
        source: bytes,
        data_attestation: WorkspaceDataAttestation | None,
    ) -> str | None:
        if len(source) > MAX_EGRESS_BLOCK_BYTES:
            return "egress_block_too_large"
        if not policy.policy_id or not policy.revision:
            return "egress_policy_invalid"
        if block.data_class not in _KNOWN_DATA_CLASSES or block.data_class in _ALWAYS_DENIED_DATA_CLASSES:
            return "egress_data_class_denied"
        if block.data_class == "workspace_internal_fake":
            attestation_reason = _fake_data_attestation_denial(
                block,
                data_attestation,
            )
            if attestation_reason is not None:
                return attestation_reason
        if block.provenance not in _KNOWN_PROVENANCE:
            return "egress_provenance_unknown"
        if block.trust_level not in _KNOWN_TRUST:
            return "egress_trust_unknown"
        if block.data_class not in policy.allowed_data_classes:
            return "egress_data_class_not_allowed"
        if not destination_provider_id or destination_provider_id not in policy.allowed_provider_ids:
            return "egress_destination_denied"
        if policy.allowed_upstream_ids:
            if destination_upstream_id not in policy.allowed_upstream_ids:
                return "egress_upstream_denied"
        elif destination_upstream_id is not None:
            return "egress_upstream_denied"
        return None

    def _audit(self, workspace_id: str, decision: AgenticEgressDecision) -> None:
        if self.observability_store is None:
            return
        record_platform_audit(
            self.observability_store,
            action="runtime.egress.decision",
            status="succeeded" if decision.export_allowed else "failed",
            source_domain="egress",
            detail=decision.reason_code,
            workspace_id=workspace_id,
            runtime_session_id=decision.session_id,
            provider_id=decision.destination_provider_id or None,
            payload=asdict(decision),
            now=decision.decided_at,
        )


def public_remote_egress_policy(
    *,
    provider_id: str,
    upstream_ids: tuple[str, ...] = (),
    policy_id: str = "public-remote-egress",
    revision: str = "1",
) -> AgenticEgressPolicy:
    """Return a fixture-safe policy that can export only Core-classified public data."""
    return AgenticEgressPolicy(
        policy_id=policy_id,
        revision=revision,
        allowed_data_classes=("public",),
        allowed_provider_ids=(provider_id,),
        allowed_upstream_ids=upstream_ids,
    )


def _fake_data_attestation_denial(
    block: AgenticEgressContentBlock,
    attestation: WorkspaceDataAttestation | None,
) -> str | None:
    """Require both actual resource classification and a separate declaration."""
    if attestation is None:
        return "egress_fake_data_attestation_required"
    if attestation.workspace_id != block.workspace_id:
        return "egress_fake_data_attestation_workspace_mismatch"
    if attestation.status == "revoked" and attestation.well_formed:
        return "egress_fake_data_attestation_revoked"
    if not attestation.authoritative:
        return "egress_fake_data_attestation_invalid"
    if (
        not block.source_ref
        or not block.source_revision
        or not block.resource_identity
        or not isinstance(block.classification_revision, int)
        or block.classification_revision < 1
    ):
        return "egress_fake_data_classification_unverified"
    if not attestation.covers_resource(block.source_ref):
        return "egress_fake_data_attestation_scope_denied"
    return None


def _content_digest(key: bytes, content: bytes) -> str:
    return hmac.new(key, _DIGEST_DOMAIN + content, hashlib.sha256).hexdigest()
