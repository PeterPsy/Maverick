"""Immutable experimental grants; no credential values or certificate claims."""

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
import re

from core.certification_lab.errors import LabAuthorizationError
from core.providers.agentic_models import AgenticRuntimePolicy, RoutingConstraint
from core.providers.capability_models import RuntimeCapabilitySet


def require_digest(value: str, *, length: int = 64) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{%d}" % length, value) is None:
        raise LabAuthorizationError("lab_permit_invalid")


def require_id(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}", value) is None:
        raise LabAuthorizationError("lab_permit_invalid")


@dataclass(frozen=True)
class LabApiTarget:
    definition_id: str
    definition_revision: str
    definition_digest: str
    model_provider_id: str
    endpoint_url: str
    scope: str = "api_profile"


@dataclass(frozen=True)
class LabNativeTarget:
    runtime_engine_id: str
    model_provider_id: str
    connection_id: str
    connection_digest: str
    distribution_digest: str
    binary_digest: str
    effects_digest: str
    scope: str = "native_connection"


@dataclass(frozen=True)
class LabCandidateIdentity:
    source_commit: str
    adapter_id: str
    adapter_version: str
    adapter_artifact_digest: str
    tcb_manifest_id: str
    tcb_manifest_version: str
    tcb_structure_digest: str
    tcb_live_digest: str


@dataclass(frozen=True)
class LabSessionGrant:
    session_id: str
    scenario_id: str
    parent_session_id: str | None = None


@dataclass(frozen=True)
class LabWorkspaceScope:
    workspace_id: str
    root_path: str
    root_identity: str
    attestation_id: str
    attestation_revision: int
    actor_id: str
    sessions: tuple[LabSessionGrant, ...]


@dataclass(frozen=True)
class LabBudgetScope:
    ledger_identity: str
    policy_digest: str
    pricing_digest: str
    max_cost_microusd: int
    max_requests: int


@dataclass(frozen=True)
class LabExecutionPermit:
    permit_id: str
    job_id: str
    installation_id: str
    issuer_key_id: str
    operator_authorization_ref: str
    target: LabApiTarget | LabNativeTarget
    candidate: LabCandidateIdentity
    workspace: LabWorkspaceScope
    reasoning_efforts: tuple[str, ...]
    capability_ceiling: RuntimeCapabilitySet
    policy_ceiling: AgenticRuntimePolicy
    routing_constraint: RoutingConstraint
    egress_policy_id: str
    egress_policy_revision: str
    credential_binding_id: str
    credential_binding_digest: str
    budget: LabBudgetScope
    max_concurrent_sessions: int
    issued_at: datetime
    expires_at: datetime
    schema: str = "maverick-lab-execution-permit.v1"
    purpose: str = "certification_lab"

    def validate(self) -> None:
        from core.runtime.authority import intersect_runtime_policies

        if self.schema != "maverick-lab-execution-permit.v1" or self.purpose != "certification_lab":
            raise LabAuthorizationError("lab_permit_invalid")
        for value in (self.permit_id, self.job_id, self.installation_id, self.issuer_key_id,
                      self.egress_policy_id, self.egress_policy_revision, self.credential_binding_id):
            require_id(value)
        require_digest(self.operator_authorization_ref)
        require_digest(self.credential_binding_digest)
        require_digest(self.candidate.source_commit, length=40)
        for field in fields(self.candidate):
            value = getattr(self.candidate, field.name)
            if field.name.endswith("digest"):
                require_digest(value)
            elif field.name != "source_commit":
                require_id(value)
        _validate_target(self.target)
        scope = self.workspace
        for value in (scope.workspace_id, scope.actor_id, scope.attestation_id):
            require_id(value)
        require_digest(scope.root_identity)
        if (not isinstance(scope.root_path, str) or not scope.root_path.startswith("/")
                or type(scope.attestation_revision) is not int or scope.attestation_revision < 1
                or not isinstance(scope.sessions, tuple) or not 1 <= len(scope.sessions) <= 128):
            raise LabAuthorizationError("lab_permit_invalid")
        session_ids = {item.session_id for item in scope.sessions}
        if len(session_ids) != len(scope.sessions):
            raise LabAuthorizationError("lab_permit_invalid")
        parents = {}
        for grant in scope.sessions:
            require_id(grant.session_id)
            require_id(grant.scenario_id)
            if grant.parent_session_id is not None and grant.parent_session_id not in session_ids:
                raise LabAuthorizationError("lab_permit_invalid")
            parents[grant.session_id] = grant.parent_session_id
        for session_id in parents:
            seen = set()
            while session_id is not None:
                if session_id in seen:
                    raise LabAuthorizationError("lab_permit_invalid")
                seen.add(session_id)
                session_id = parents[session_id]
        if (type(self.max_concurrent_sessions) is not int
                or not 1 <= self.max_concurrent_sessions <= len(scope.sessions)
                or not isinstance(self.reasoning_efforts, tuple) or not self.reasoning_efforts
                or len(set(self.reasoning_efforts)) != len(self.reasoning_efforts)):
            raise LabAuthorizationError("lab_permit_invalid")
        for effort in self.reasoning_efforts:
            require_id(effort)
        for field in fields(self.capability_ceiling):
            value = getattr(self.capability_ceiling, field.name)
            if field.name != "attachment_modalities" and type(value) is not bool:
                raise LabAuthorizationError("lab_permit_invalid")
        if not isinstance(self.capability_ceiling.attachment_modalities, tuple):
            raise LabAuthorizationError("lab_permit_invalid")
        intersect_runtime_policies(self.policy_ceiling)
        if (not self.policy_ceiling.allowed_remote_data_classes
                or set(self.policy_ceiling.allowed_remote_data_classes) - {"public", "workspace_internal_fake"}
                or self.routing_constraint.allow_fallbacks
                or not self.routing_constraint.require_parameters
                or (self.target.model_provider_id == "openrouter" and not self.routing_constraint.allowed_upstream_ids)):
            raise LabAuthorizationError("lab_permit_invalid")
        budget = self.budget
        for value in (budget.ledger_identity, budget.policy_digest, budget.pricing_digest):
            require_digest(value)
        if (type(budget.max_requests) is not int or not 1 <= budget.max_requests <= 200
                or type(budget.max_cost_microusd) is not int
                or (self.target.model_provider_id == "openrouter" and not 0 < budget.max_cost_microusd <= 4_500_000)
                or (self.target.model_provider_id in {"google-ai-studio", "google"}
                    and (budget.max_cost_microusd != 0 or budget.max_requests > 80))):
            raise LabAuthorizationError("lab_permit_invalid")
        if (not isinstance(self.issued_at, datetime) or self.issued_at.tzinfo is None
                or not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None
                or not timedelta(0) < self.expires_at - self.issued_at <= timedelta(hours=24)):
            raise LabAuthorizationError("lab_permit_invalid")


def _validate_target(target):
    if type(target) is LabApiTarget:
        if target.scope != "api_profile" or target.model_provider_id not in {"google-ai-studio", "openrouter"}:
            raise LabAuthorizationError("lab_target_invalid")
        require_id(target.definition_id)
        require_id(target.definition_revision)
        require_digest(target.definition_digest)
        endpoints = {"google-ai-studio": "https://generativelanguage.googleapis.com/v1/interactions?alt=sse",
                     "openrouter": "https://openrouter.ai/api/v1/chat/completions"}
        if target.endpoint_url != endpoints[target.model_provider_id]:
            raise LabAuthorizationError("lab_target_invalid")
    elif type(target) is LabNativeTarget:
        if (target.scope != "native_connection" or target.runtime_engine_id != "gemini-cli"
                or target.model_provider_id != "google"):
            raise LabAuthorizationError("lab_target_invalid")
        require_id(target.connection_id)
        for value in (target.connection_digest, target.distribution_digest, target.binary_digest, target.effects_digest):
            require_digest(value)
    else:
        raise LabAuthorizationError("lab_target_invalid")
