"""Synthetic signed grants for isolated boundary tests; no active authority."""

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from core.certification_lab.permit import (
    LabApiTarget, LabBudgetScope, LabCandidateIdentity, LabExecutionPermit,
    LabSessionGrant, LabWorkspaceScope,
)
from core.certification_lab.permit_codec import sign_lab_permit
from core.certification_lab.permit_store import LabPermitStore
from core.certification_lab.trust import LabPermitTrust
from core.providers.certification_target import builtin_api_certification_profile, api_profile_target_digest
from core.providers.maverick_agent_builtins import builtin_maverick_agent_publications
from core.providers.capability_models import RuntimeCapabilitySet


def permit_fixture(root):
    os.chmod(root, 0o700)
    key = Ed25519PrivateKey.generate()
    trust_path = root / "trust.json"
    trust_path.write_text(json.dumps({
        "schema": "maverick-lab-issuer-trust.v1", "installation_id": "offline-lab",
        "issuers": {"offline-issuer": {
            "public_key": base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode(),
            "operator_authorization_refs": ["a" * 64],
        }},
    }))
    os.chmod(trust_path, 0o600)
    trust = LabPermitTrust(trust_path, "offline-lab")
    store = LabPermitStore.create(root / "permits.sqlite", trust=trust)
    profile = builtin_api_certification_profile("openrouter")
    publication = next(p for p in builtin_maverick_agent_publications() if p.profile.definition_id == profile.definition_id)
    now = datetime.now(UTC)
    permit = LabExecutionPermit(
        permit_id="offline-permit", job_id="offline-job", installation_id="offline-lab",
        issuer_key_id="offline-issuer", operator_authorization_ref="a" * 64,
        target=LabApiTarget(profile.definition_id, profile.revision, api_profile_target_digest(profile),
                            "openrouter", publication.provider_config.endpoint_url),
        candidate=LabCandidateIdentity("a" * 40, profile.adapter_id, "offline-version", "b" * 64,
                                       "offline-tcb", "1", "c" * 64, "d" * 64),
        workspace=LabWorkspaceScope("synthetic", str(root / "synthetic"), "e" * 64,
                                    "offline-attestation", 1, "offline-member", (LabSessionGrant("one", "nested-edit"),)),
        reasoning_efforts=publication.recipe.support_flags.reasoning_efforts,
        capability_ceiling=RuntimeCapabilitySet(
            streaming=True, tool_orchestration=True, cli=True, mcp=True, skill_catalog=True,
            filesystem_list=True, filesystem_read=True, filesystem_write=True, shell=True,
            interrupt=True, same_turn_steering=True, recovery=True, confirmation_resume=True,
            provider_private_state=True, attachment_modalities=(), app_references=True, confirmations=True,
        ),
        policy_ceiling=replace(profile.policy_ceiling, allowed_remote_data_classes=("public", "workspace_internal_fake")),
        routing_constraint=profile.routing_constraint,
        egress_policy_id=profile.egress_policy_id, egress_policy_revision=profile.egress_policy_revision,
        credential_binding_id="offline-credential", credential_binding_digest="f" * 64,
        budget=LabBudgetScope("a" * 64, "b" * 64, "c" * 64, 4_500_000, 200),
        max_concurrent_sessions=1, issued_at=now, expires_at=now + timedelta(minutes=30),
    )
    return store, key, permit


def installed_permit(root):
    store, key, permit = permit_fixture(root)
    return store, key, permit, store.install(sign_lab_permit(permit, private_key=key))
