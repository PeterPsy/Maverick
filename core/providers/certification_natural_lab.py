"""Signed, isolated authority for real pre-certificate natural conformance.

This module does not create a capability certificate and is never wired by the
production bootstrap.  Its permit only admits one exact API profile inside a
disposable installation while the ordinary hosted loop, tools, egress policy,
credential resolution, journals, and cleanup remain in use.
"""

from __future__ import annotations

import base64
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
import subprocess
from threading import RLock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from core.providers.capability_models import RuntimeCapabilitySet
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certification_budget_ledger import CertificationBudgetLedger
from core.providers.certification_job_budget import (
    CertificationGenerationLimits,
    CertificationJobTransport,
)
from core.providers.certification_target import api_profile_target_digest
from core.providers.certified_execution_tcb import (
    certified_tcb_identity,
    certified_tcb_revision_fence,
)
from core.providers.errors import CapabilityCertificateError
from core.providers.google_interactions_client import GoogleInteractionsAgenticClient
from core.providers.openrouter_agentic_client import OpenRouterAgenticClient
from core.providers.provider_credentials import resolve_provider_binding
from core.runtime.authority import (
    EffectiveRuntimeAuthority,
    intersect_runtime_policies,
    runtime_feature_flag_revision,
)
from core.runtime.execution_binding import canonical_digest
from core.runtime.full_workspace_contract import (
    validate_full_workspace_live_authority,
)
from core.runtime.hosted_agentic_policy import authorized_core_tool_handles
from core.runtime.hosted_provider_runtime import HostedProviderRuntimeRegistry


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class CertificationNaturalLabPermit:
    """Narrow operator grant; deliberately not a release certificate."""

    schema: str
    permit_id: str
    authorization_ref: str
    source_commit: str
    repository_root_identity: str
    target_digest: str
    adapter_artifact_digest: str
    tcb_manifest_id: str
    tcb_manifest_version: str
    tcb_structure_digest: str
    tcb_live_digest: str
    workspace_id: str
    workspace_root: str
    workspace_root_identity: str
    actor_user_id: str
    definition_id: str
    definition_revision: str
    workspace_binding_id: str
    credential_binding_digest: str
    reasoning_effort: str
    ledger_policy_digest: str
    run_id: str
    reviewer_ref: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class SignedCertificationNaturalLabPermit:
    permit: CertificationNaturalLabPermit
    signer_key_id: str
    signature: str


def directory_identity(path: Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise CapabilityCertificateError("certification_lab_path_invalid")
    try:
        resolved = candidate.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as error:
        raise CapabilityCertificateError("certification_lab_path_invalid") from error
    if resolved != candidate:
        raise CapabilityCertificateError("certification_lab_path_invalid")
    return canonical_digest(
        {
            "path": str(resolved),
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "owner": metadata.st_uid,
        }
    )


def sign_certification_natural_lab_permit(
    permit: CertificationNaturalLabPermit,
    *,
    signer_key_id: str,
    private_key: Ed25519PrivateKey,
) -> SignedCertificationNaturalLabPermit:
    _validate_permit_shape(permit, now=datetime.now(tz=UTC))
    key_id = str(signer_key_id or "").strip()
    if not key_id:
        raise CapabilityCertificateError("certification_lab_signer_missing")
    return SignedCertificationNaturalLabPermit(
        permit=permit,
        signer_key_id=key_id,
        signature=base64.b64encode(
            private_key.sign(certification_natural_lab_permit_payload(permit))
        ).decode("ascii"),
    )


def verify_certification_natural_lab_permit(
    signed: SignedCertificationNaturalLabPermit,
    *,
    trusted_keys: dict[str, Ed25519PublicKey],
    now: datetime | None = None,
) -> CertificationNaturalLabPermit:
    timestamp = now or datetime.now(tz=UTC)
    _validate_permit_shape(signed.permit, now=timestamp)
    public_key = trusted_keys.get(str(signed.signer_key_id or ""))
    if public_key is None:
        raise CapabilityCertificateError("certification_lab_signer_untrusted")
    try:
        signature = base64.b64decode(signed.signature, validate=True)
        public_key.verify(
            signature,
            certification_natural_lab_permit_payload(signed.permit),
        )
    except (InvalidSignature, ValueError) as error:
        raise CapabilityCertificateError("certification_lab_signature_invalid") from error
    return signed.permit


def certification_natural_lab_permit_payload(
    permit: CertificationNaturalLabPermit,
) -> bytes:
    payload = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in asdict(permit).items()
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class CertificationNaturalLabAuthority:
    """Verified authority used only by an explicitly injected hosted adapter."""

    def __init__(
        self,
        *,
        signed_permit: SignedCertificationNaturalLabPermit,
        trusted_keys: dict[str, Ed25519PublicKey],
        state,
        ledger: CertificationBudgetLedger,
        credential_fingerprint_key: bytes,
    ) -> None:
        self.permit = verify_certification_natural_lab_permit(
            signed_permit,
            trusted_keys=trusted_keys,
        )
        if not isinstance(ledger, CertificationBudgetLedger):
            raise CapabilityCertificateError("certification_budget_ledger_required")
        if len(credential_fingerprint_key) < 32:
            raise CapabilityCertificateError("certification_lab_key_invalid")
        self.state = state
        self.ledger = ledger
        self._credential_fingerprint_key = bytes(credential_fingerprint_key)
        self._adapter = None
        self._tcb_revision_fence = ""
        self._active_context: ContextVar[object | None] = ContextVar(
            f"certification_natural_lab_context_{self.permit.permit_id}",
            default=None,
        )
        self._lock = RLock()
        self._validate_installation()

    def bind_adapter(self, adapter) -> None:
        with self._lock:
            if self._adapter is not None:
                raise CapabilityCertificateError("certification_lab_adapter_already_bound")
            self._adapter = adapter
            self.validate_candidate()
            self._tcb_revision_fence = certified_tcb_revision_fence(
                self.state.repository_root
            )

    def validate_candidate(self) -> None:
        permit = self.permit
        root = Path(self.state.repository_root)
        if _git_commit(root) != permit.source_commit or _git_dirty(root):
            raise CapabilityCertificateError("certification_lab_source_drift")
        tcb = certified_tcb_identity(root)
        if (
            tcb.manifest_id != permit.tcb_manifest_id
            or tcb.manifest_version != permit.tcb_manifest_version
            or tcb.structure_digest != permit.tcb_structure_digest
            or tcb.live_digest != permit.tcb_live_digest
        ):
            raise CapabilityCertificateError("certification_lab_tcb_drift")
        if self._adapter is not None and (
            runtime_adapter_artifact_digest(self._adapter)
            != permit.adapter_artifact_digest
        ):
            raise CapabilityCertificateError("certification_lab_adapter_drift")

    def resolve(self, context) -> EffectiveRuntimeAuthority:
        definition, workspace_binding, policy = self._validate_context(context)
        handles = tuple(authorized_core_tool_handles(context.binding))
        capabilities = _api_agentic_capabilities()
        validate_full_workspace_live_authority(
            revision=context.binding.full_workspace_contract_revision,
            capabilities=capabilities,
            policy=policy,
            allowed_handles=handles,
        )
        now = datetime.now(tz=UTC)
        authority = EffectiveRuntimeAuthority(
            execution_binding_id=context.binding.execution_binding_id,
            turn_id=context.correlation_id,
            certificate_id=f"certification-lab:{self.permit.permit_id}",
            allowed_capabilities=capabilities,
            allowed_tool_handles=handles,
            execution_mode=context.session.effective_mode,
            egress_policy_id=context.binding.egress_policy_id,
            policy_revision_set=(
                f"profile:{definition.definition_id}:{definition.revision}",
                f"workspace-live:{workspace_binding.binding_id}:{workspace_binding.revision}",
                f"lab-permit:{self.permit.permit_id}",
                f"egress:{context.binding.egress_policy_id}:{context.binding.egress_policy_revision}",
            ),
            health_revision="runtime-health:certification-lab-validated",
            authority_digest="",
            computed_at=now,
            actor_policy_allowed=True,
            actor_policy_revision=f"certification-lab-actor:{self.permit.actor_user_id}",
            feature_flag_revision=runtime_feature_flag_revision(context.binding),
            provider_health_status="healthy",
            provider_id=context.binding.model_provider_id,
            model_id=context.binding.model_id,
            model_revision=context.binding.model_revision,
            model_revision_policy=context.binding.model_revision_policy,
            provider_protocol=context.binding.provider_protocol,
            certified_upstream_ids=tuple(definition.routing_constraint.allowed_upstream_ids),
            effective_upstream_ids=tuple(context.binding.routing_constraint_snapshot.allowed_upstream_ids),
            allowed_remote_data_classes=policy.allowed_remote_data_classes,
            data_collection_policy=context.binding.routing_constraint_snapshot.data_collection_policy,
            require_zdr=context.binding.routing_constraint_snapshot.require_zdr,
            certificate_suite_id="certification-natural-lab",
            certificate_suite_version="1",
            certificate_expires_at=self.permit.expires_at,
            tcb_manifest_id=self.permit.tcb_manifest_id,
            tcb_manifest_version=self.permit.tcb_manifest_version,
            tcb_structure_digest=self.permit.tcb_structure_digest,
            tcb_live_digest=self.permit.tcb_live_digest,
            tcb_revision_fence=self._tcb_revision_fence,
            tcb_posture="experimental",
            full_workspace_contract_revision=context.binding.full_workspace_contract_revision,
            execution_family=context.binding.execution_family,
            harness_recipe_id=context.binding.harness_recipe_id,
            harness_recipe_revision=context.binding.harness_recipe_revision,
            harness_recipe_digest=context.binding.harness_recipe_digest,
            provider_capability_catalog_digest=context.binding.provider_capability_catalog_digest,
            semantic_projection_compiler_revision=context.binding.semantic_projection_compiler_revision,
            tool_contract_revision=context.binding.tool_contract_revision,
            context_policy_revision=(
                ""
                if context.binding.context_policy_snapshot is None
                else context.binding.context_policy_snapshot.revision
            ),
        )
        authority = replace(authority, authority_digest=canonical_digest(authority))
        self._active_context.set(context)
        return authority

    def revalidate(self, context, authority) -> EffectiveRuntimeAuthority:
        self._validate_context(context)
        if (
            authority.execution_binding_id != context.binding.execution_binding_id
            or authority.turn_id != context.correlation_id
            or authority.certificate_id != f"certification-lab:{self.permit.permit_id}"
            or authority.authority_digest != canonical_digest(authority)
            or authority.tcb_revision_fence != self._tcb_revision_fence
            or certified_tcb_revision_fence(self.state.repository_root)
            != self._tcb_revision_fence
        ):
            raise CapabilityCertificateError("certification_lab_authority_changed")
        return authority

    def transport_authorization(self):
        return _CertificationNaturalTransportAuthorization(self)

    def _validate_installation(self) -> None:
        permit = self.permit
        root = Path(self.state.repository_root)
        workspace_root = Path(permit.workspace_root)
        if (
            root.resolve(strict=True) != root
            or directory_identity(root) != permit.repository_root_identity
            or workspace_root.parent != root / "workspaces"
            or workspace_root.name != permit.workspace_id
            or directory_identity(workspace_root) != permit.workspace_root_identity
            or self.ledger.authorization_ref != permit.authorization_ref
            or self.ledger.policy_digest != permit.ledger_policy_digest
        ):
            raise CapabilityCertificateError("certification_lab_installation_mismatch")
        self.validate_candidate()

    def _validate_context(self, context):
        permit = self.permit
        if datetime.now(tz=UTC) >= permit.expires_at:
            raise CapabilityCertificateError("certification_lab_permit_expired")
        binding = context.binding
        session = context.session
        if (
            session.session_id != binding.session_id
            or session.workspace_id != permit.workspace_id
            or session.workspace_root != permit.workspace_root
            or session.owner_user_id != permit.actor_user_id
            or session.created_by_user_id != permit.actor_user_id
            or session.effective_mode != "full-access"
            or session.status not in {"created", "running"}
            or binding.binding_digest != canonical_digest(binding)
            or binding.capability_certificate_id
            != f"certification-lab:{permit.permit_id}"
            or binding.certificate_evidence_digest
            != hashlib.sha256(certification_natural_lab_permit_payload(permit)).hexdigest()
            or binding.profile_definition_id != permit.definition_id
            or binding.profile_definition_revision != permit.definition_revision
            or binding.workspace_binding_id != permit.workspace_binding_id
            or binding.reasoning_effort != permit.reasoning_effort
            or binding.adapter_artifact_digest != permit.adapter_artifact_digest
            or binding.tcb_manifest_id != permit.tcb_manifest_id
            or binding.tcb_manifest_version != permit.tcb_manifest_version
            or binding.tcb_structure_digest != permit.tcb_structure_digest
            or binding.tcb_live_digest != permit.tcb_live_digest
        ):
            raise CapabilityCertificateError("certification_lab_binding_mismatch")
        persisted = self.state.runtime_store.get_session(session.session_id)
        if persisted.execution_binding != binding or persisted.workspace_root != permit.workspace_root:
            raise CapabilityCertificateError("certification_lab_session_changed")
        definition = self.state.provider_store.get_agentic_profile_definition(
            permit.definition_id,
            permit.definition_revision,
        )
        if api_profile_target_digest(definition) != permit.target_digest:
            raise CapabilityCertificateError("certification_lab_target_drift")
        workspace_binding = self.state.provider_store.get_workspace_agentic_profile_binding(
            permit.workspace_binding_id
        )
        if (
            not workspace_binding.enabled
            or workspace_binding.workspace_id != permit.workspace_id
            or workspace_binding.definition_id != permit.definition_id
            or workspace_binding.definition_revision != permit.definition_revision
            or workspace_binding.credential_binding_id != binding.credential_binding_id
        ):
            raise CapabilityCertificateError("certification_lab_workspace_binding_changed")
        credential = resolve_provider_binding(
            self.state.provider_store,
            provider_id=binding.model_provider_id,
            workspace_id=permit.workspace_id,
            binding_id=binding.credential_binding_id,
        )
        if credential is None or canonical_digest(credential) != permit.credential_binding_digest:
            raise CapabilityCertificateError("certification_lab_credential_binding_changed")
        status = self.ledger.status().get(binding.model_provider_id)
        if status is None or status["halt_reason"] is not None:
            raise CapabilityCertificateError("certification_budget_halted")
        policy = intersect_runtime_policies(
            binding.profile_policy_ceiling_snapshot,
            binding.workspace_policy_ceiling_snapshot,
            workspace_binding.workspace_policy_ceiling,
        )
        return definition, workspace_binding, policy

    def _revalidate_transport_credential(self, credential) -> None:
        context = self._active_context.get()
        if context is None:
            raise CapabilityCertificateError("certification_lab_authority_unavailable")
        self._validate_context(context)
        if credential is None:
            raise CapabilityCertificateError("certification_lab_credential_changed")
        from core.runtime.hosted_agentic_factory import _credential

        current = _credential(self.state, context)
        if current is None or not hmac.compare_digest(
            self._credential_fingerprint(credential.reveal()),
            self._credential_fingerprint(current.reveal()),
        ):
            raise CapabilityCertificateError("certification_lab_credential_changed")

    def _credential_fingerprint(self, value: str) -> bytes:
        return hmac.new(
            self._credential_fingerprint_key,
            value.encode("utf-8"),
            hashlib.sha256,
        ).digest()


class _CertificationNaturalTransportAuthorization:
    def __init__(self, authority: CertificationNaturalLabAuthority) -> None:
        self.authority = authority

    def revalidate(self, credential) -> None:
        self.authority._revalidate_transport_credential(credential)


class _CertificationNaturalBudgetedTransport:
    def __init__(self, transport, *, authority, config, recipe) -> None:
        self.transport = transport
        self.endpoint = transport.endpoint
        self.authority = authority
        self.config = config
        self.recipe = recipe

    async def stream(self, *, payload, credential):
        context = self.authority._active_context.get()
        if (
            context is None
            or self.config.model_provider_id != context.binding.model_provider_id
            or self.config.endpoint_url != self.endpoint
            or self.config.digest != context.binding.provider_config_digest
        ):
            raise CapabilityCertificateError("certification_lab_generation_target_mismatch")
        if self.config.model_provider_id == "google-ai-studio" and payload.get(
            "previous_interaction_id"
        ):
            raise CapabilityCertificateError("certification_lab_stateful_generation_forbidden")
        fence = CertificationJobTransport(
            self.transport,
            ledger=self.authority.ledger,
            run_id=self.authority.permit.run_id,
            pricing=self.config.token_cost_policy,
            authorization=self.authority.transport_authorization(),
            limits=CertificationGenerationLimits(
                provider_id=self.config.model_provider_id,
                model_id=self.recipe.model_id,
                endpoint=self.config.endpoint_url,
                max_input_tokens=self.recipe.context_policy.max_request_input_tokens,
                max_output_tokens=self.recipe.support_flags.output_token_limit,
                pricing_digest=canonical_digest(self.config.token_cost_policy),
            ),
        )
        async for event in fence.stream(payload=payload, credential=credential):
            yield event


def build_certification_natural_runtime_registry(
    authority: CertificationNaturalLabAuthority,
) -> HostedProviderRuntimeRegistry:
    """Clone the code-owned registry while fencing every raw HTTP transport."""
    from core.runtime.hosted_runtime_registry_builder import (
        build_hosted_provider_runtime_registry,
    )

    base = build_hosted_provider_runtime_registry(
        onboarding_catalog=authority.state.maverick_agent_onboarding_catalog,
    )
    result = HostedProviderRuntimeRegistry()
    for runtime in base.runtimes():
        client = runtime.client
        if runtime.model_provider_id == authority.state.provider_store.get_agentic_profile_definition(
            authority.permit.definition_id,
            authority.permit.definition_revision,
        ).model_provider_id:
            publication = next(
                item
                for item in authority.state.maverick_agent_onboarding_catalog.publications()
                if item.profile.definition_id == authority.permit.definition_id
                and item.profile.revision == authority.permit.definition_revision
            )
            transport = _CertificationNaturalBudgetedTransport(
                client.transport,
                authority=authority,
                config=publication.provider_config,
                recipe=publication.recipe,
            )
            if isinstance(client, GoogleInteractionsAgenticClient):
                client = GoogleInteractionsAgenticClient(
                    model_id=client.model_id,
                    state_mode=client.state_mode,
                    transport=transport,
                    token_cost_policy=client.token_cost_policy,
                    routing_constraint=client.routing_constraint,
                    allowed_upstream_ids=client.allowed_upstream_ids,
                    upstream_provider_names=client.upstream_provider_names,
                    resolved_model_ids=client.resolved_model_ids,
                )
            elif isinstance(client, OpenRouterAgenticClient):
                client = OpenRouterAgenticClient(
                    model_id=client.model_id,
                    transport=transport,
                    token_cost_policy=client.token_cost_policy,
                    routing_constraint=client.routing_constraint,
                    allowed_upstream_ids=client.allowed_upstream_ids,
                    upstream_provider_names=client.upstream_provider_names,
                    resolved_model_ids=client.resolved_model_ids,
                )
            else:
                raise CapabilityCertificateError(
                    "certification_lab_provider_unsupported"
                )
        result.register(replace(runtime, client=client))
    return result


def _api_agentic_capabilities() -> RuntimeCapabilitySet:
    return RuntimeCapabilitySet(
        streaming=True,
        tool_orchestration=True,
        cli=True,
        mcp=True,
        skill_catalog=True,
        filesystem_list=True,
        filesystem_read=True,
        filesystem_write=True,
        shell=True,
        interrupt=True,
        same_turn_steering=False,
        recovery=True,
        confirmation_resume=True,
        provider_private_state=True,
        attachment_modalities=("file",),
        app_references=True,
        confirmations=True,
    )


def _validate_permit_shape(
    permit: CertificationNaturalLabPermit,
    *,
    now: datetime,
) -> None:
    if permit.schema != "maverick-certification-natural-lab-permit.v1":
        raise CapabilityCertificateError("certification_lab_permit_invalid")
    for value in (
        permit.authorization_ref,
        permit.repository_root_identity,
        permit.target_digest,
        permit.adapter_artifact_digest,
        permit.tcb_structure_digest,
        permit.tcb_live_digest,
        permit.workspace_root_identity,
        permit.credential_binding_digest,
        permit.ledger_policy_digest,
        permit.reviewer_ref,
    ):
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise CapabilityCertificateError("certification_lab_permit_invalid")
    if not isinstance(permit.source_commit, str) or _COMMIT.fullmatch(
        permit.source_commit
    ) is None:
        raise CapabilityCertificateError("certification_lab_permit_invalid")
    for value in (
        permit.permit_id,
        permit.tcb_manifest_id,
        permit.tcb_manifest_version,
        permit.workspace_id,
        permit.actor_user_id,
        permit.definition_id,
        permit.definition_revision,
        permit.workspace_binding_id,
        permit.reasoning_effort,
        permit.run_id,
    ):
        if not isinstance(value, str) or not value or len(value) > 160:
            raise CapabilityCertificateError("certification_lab_permit_invalid")
    if (
        permit.issued_at.tzinfo is None
        or permit.expires_at.tzinfo is None
        or not permit.issued_at <= now < permit.expires_at
        or (permit.expires_at - permit.issued_at).total_seconds() > 86_400
        or not Path(permit.workspace_root).is_absolute()
    ):
        raise CapabilityCertificateError("certification_lab_permit_invalid")


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    value = result.stdout.strip()
    if result.returncode or _COMMIT.fullmatch(value) is None:
        raise CapabilityCertificateError("certification_lab_source_unavailable")
    return value


def _git_dirty(root: Path) -> bool:
    result = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=normal"),
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise CapabilityCertificateError("certification_lab_source_unavailable")
    return bool(result.stdout.strip())


__all__ = [
    "CertificationNaturalLabAuthority",
    "CertificationNaturalLabPermit",
    "SignedCertificationNaturalLabPermit",
    "build_certification_natural_runtime_registry",
    "certification_natural_lab_permit_payload",
    "directory_identity",
    "sign_certification_natural_lab_permit",
    "verify_certification_natural_lab_permit",
]
