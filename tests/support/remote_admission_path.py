"""Offline admission fixture: real stores, guards, certificates and composition.

Only the certification observations are fabricated. No live conformance or
release approval is claimed, and no provider transport is opened here.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_models import default_actor_selection_policy
from core.providers.agentic_profiles import build_pinned_execution_binding
from core.providers.agentic_workspace_admin import save_workspace_agentic_binding
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.certification_pipeline import execute_certification_suite, sign_certification_run
from core.providers.openrouter_agentic_certification import (
    OPENROUTER_CERTIFICATION_SUITE_ID, OPENROUTER_CERTIFICATION_SUITE_VERSION,
    publish_openrouter_preview_certificate,
)
from core.providers.openrouter_agentic_profile import OPENROUTER_AGENTIC_PROFILE_ID, OPENROUTER_AGENTIC_PROFILE_REVISION
from core.providers.provider_credentials import bind_provider_credential
from core.workspaces.data_governance import issue_fake_data_attestation
from tests.support.certification_evidence import fixture_step_process, with_fixture_behavior, fixture_publication_authority
from tests.support.repo import make_temp_repo_root


def admitted_fixture(test, *, is_default=False):
    test.enterContext(patch.dict("os.environ", {
        "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1", "MAVERICK_FEATURE_HOSTED_AGENT_RUNTIME": "1",
        "MAVERICK_FEATURE_OPENROUTER_AGENTIC_PREVIEW": "1",
    }))
    # Exercise the future product-positive gate, without replacing ANY guard.
    # This is deliberately not a lab grant or an operational release decision.
    test.enterContext(patch("core.runtime.remote_agentic_admission.REMOTE_AGENTIC_ATTESTATION_AVAILABLE", True))
    now = datetime.now(UTC)
    root = make_temp_repo_root(test)
    test.enterContext(patch.dict("os.environ", {
        "MAVERICK_CONTROL_STORE": "json",
        "MAVERICK_JSON_CONTROL_STORE_ROOT": str(root / "data" / "control-plane" / "json"),
    }))
    state = bootstrap_platform_state(start_path=root, install_builtin_apps=False)
    profile = state.provider_store.get_agentic_profile_definition(OPENROUTER_AGENTIC_PROFILE_ID, OPENROUTER_AGENTIC_PROFILE_REVISION)
    adapter = state.provider_registry.get_agentic_runtime_adapter(profile.runtime_engine_id)
    with patch("core.providers.certification_pipeline._require_clean_checkout"), patch(
        "core.providers.certification_pipeline._git_commit", return_value="a" * 40,
    ), patch("core.providers.certification_pipeline.subprocess.run", side_effect=fixture_step_process):
        run = execute_certification_suite(
            cwd=Path(__file__).resolve().parents[2], suite_id=OPENROUTER_CERTIFICATION_SUITE_ID,
            suite_version=OPENROUTER_CERTIFICATION_SUITE_VERSION,
            adapter_artifact_digest=runtime_adapter_artifact_digest(adapter), evidence_refs=(), started_at=now,
        )
    run = with_fixture_behavior(run)
    key = Ed25519PrivateKey.generate()
    signed = sign_certification_run(run, signer_key_id="test-ci", private_key=key)
    publisher, review = fixture_publication_authority(test, signed, key)
    with patch("core.providers.certification_pipeline._git_commit", return_value=run.source_commit):
        publish_openrouter_preview_certificate(state.provider_store, definition=profile, adapter=adapter,
                                              signed_run=signed, publisher=publisher, review=review)
    attestation = issue_fake_data_attestation(
        workspace_id="default", actor_id="offline-operator", actor_kind="platform_operator",
        scope_type="workspace", expected_revision=0, now=now,
    )
    state.workspace_store.save_data_attestation(attestation, expected_revision=0)
    credential = bind_provider_credential(state.provider_store, provider_id="openrouter", workspace_id="default",
                                         secret_ref="platform:secrets/offline-only", now=now)
    enabled = save_workspace_agentic_binding(
        state.provider_store, state.provider_registry, workspace_id="default", definition_id=profile.definition_id,
        definition_revision=profile.revision, credential_binding_id=credential.binding_id,
        enabled=True, is_default=is_default, actor_policy=default_actor_selection_policy(), policy_patch={},
        workspace_store=state.workspace_store,
    )
    binding = build_pinned_execution_binding(
        state.provider_store, state.provider_registry, session_id="admission-positive", workspace_id="default",
        execution_mode="sandbox", workspace_binding_id=enabled.binding_id, workspace_store=state.workspace_store,
    )
    return state, binding, attestation
