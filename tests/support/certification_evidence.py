"""Fabricated observations for unit tests ONLY; never operational evidence."""

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.providers.certification_behavior import BEHAVIORAL_SCENARIOS, ZERO_TOLERANCE_COUNTERS
from core.providers.certification_target import (
    api_certification_resource_limits, builtin_api_certification_profile,
    builtin_api_certification_target, builtin_api_reasoning_efforts,
)
from core.runtime.execution_binding import canonical_digest
from core.providers.evidence_store import CapabilityEvidenceBlobStore


_ARTIFACTS = TemporaryDirectory(prefix="maverick-offline-evidence-")


def fixture_artifact_store():
    return CapabilityEvidenceBlobStore(Path(_ARTIFACTS.name))


def fixture_live_receipt(provider_id, *, nonce):
    efforts = builtin_api_reasoning_efforts(provider_id)
    common = {
        "target_digest": builtin_api_certification_target(provider_id),
        "run_nonce": nonce, "succeeded": True, "reasoning_efforts": list(efforts),
    }
    if provider_id == "google-ai-studio":
        summary = {
            "reason_code": "ok", "request_count": 3, "saw_streaming": True,
            "saw_tool_call": True, "saw_filesystem_list": True, "saw_usage": True,
            "saw_private_state": True, "reasoning_efforts": list(efforts),
            "catalog_snapshots": [asdict(fixture_google_catalog_snapshot()) for _ in range(3)],
        }
        return {
            **common, **summary, "result_summary_digest": canonical_digest(summary),
            "test_run_id": "google-interactions-live:00000000-0000-0000-0000-000000000000",
        }
    return {
        **common, "request_count": 16, "filesystem_result_count": 12,
        "catalog_snapshot_digest": "a" * 64, "catalog_model_record_digest": "b" * 64,
        "catalog_zdr_record_digest": "c" * 64, "context_length": 1_048_576,
        "max_completion_tokens": 65_536, "supports_tool_choice_none": True,
        "upstream_id": "deepinfra/fp8",
    }


def fixture_google_catalog_snapshot():
    """Fabricated catalog metadata for non-network protocol/collector unit tests."""
    from core.providers.google_interactions_catalog import GoogleInteractionsCatalogSnapshot

    profile = builtin_api_certification_profile("google-ai-studio")
    projection = {
        "api_version": profile.provider_api_version, "operation_id": "CreateInteraction",
        "model_name": f"models/{profile.model_id}", "model_version": profile.model_revision,
        "input_token_limit": 1_048_576, "output_token_limit": 65_536,
        "streaming": True, "usage_accounting": True, "tool_calling": True,
        "endpoint_schema_digest": "a" * 64, "model_record_digest": "b" * 64,
    }
    return GoogleInteractionsCatalogSnapshot(**projection, catalog_snapshot_digest=canonical_digest(projection))


def fixture_step_process(command, **kwargs):
    providers = {"scripts/run_google_interactions_probe.py": "google-ai-studio",
                 "scripts/run_openrouter_agentic_probe.py": "openrouter"}
    provider = providers.get(command[-1])
    stdout = b"passed" if provider is None else json.dumps(fixture_live_receipt(
        provider, nonce=kwargs["env"]["MAVERICK_CERTIFICATION_RUN_NONCE"],
    )).encode()
    stderr = b"Ran 1 test in 0.1s\n\nOK\n" if provider is None else b""
    for content in (stdout, stderr):
        fixture_artifact_store().put(content)
    return CompletedProcess(command, 0, stdout=stdout, stderr=stderr)


def fixture_behavior_report(run, *, provider_id):
    efforts = builtin_api_reasoning_efforts(provider_id)
    limits = api_certification_resource_limits(builtin_api_certification_profile(provider_id))
    started = datetime.now(tz=UTC)
    digests = {
        field: fixture_artifact_store().put(("OFFLINE FIXTURE ONLY: " + field).encode()).rsplit(":", 1)[1]
        for field in ("prompt_digest", "trace_digest", "semantic_source_digest", "semantic_projection_digest", "effect_digest")
    }
    observations = [
        {
            "scenario_id": scenario, "reasoning_effort": effort, "passed": True,
            "checks": {check: True for check in checks},
            **digests, "resources": {key: 1 for key in limits},
        }
        for effort in efforts for scenario, checks in BEHAVIORAL_SCENARIOS.items()
    ]
    return {
        "schema": "maverick-agentic-natural-conformance.v1", "scope": "api_profile",
        "target_digest": run.target_digest, "source_commit": run.source_commit,
        "tcb_live_digest": run.tcb_live_digest, "reviewer_ref": "6" * 64,
        "started_at": started.isoformat(), "completed_at": datetime.now(tz=UTC).isoformat(),
        "reasoning_efforts": list(efforts), "observations": observations,
        "counters": {key: 0 for key in ZERO_TOLERANCE_COUNTERS},
    }


def with_fixture_behavior(run):
    from dataclasses import replace
    from core.providers.certification_manifests import get_certification_manifest
    from core.providers.certification_pipeline import attach_behavioral_evidence

    manifest = get_certification_manifest(run.suite_id, run.suite_version)
    run = replace(run, evidence_refs=(fixture_artifact_store().put(b"OFFLINE FIXTURE ONLY: collection"),))
    with patch("core.providers.certification_pipeline._git_commit", return_value=run.source_commit):
        return attach_behavioral_evidence(
            run, fixture_behavior_report(run, provider_id=manifest.provider_id),
            cwd=Path(__file__).resolve().parents[2],
            evidence_store=fixture_artifact_store(),
        )


def fixture_publication_authority(test, signed, private_key):
    """Independent test keys and retained fabricated bytes; NOT operational trust."""
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from core.providers.certification_artifacts import verify_retained_run
    from core.providers.certification_publication import (
        CertificationPublicationAuthority, CertificationReview, review_payload,
        signed_artifact_digest, artifact_manifest_digest,
    )

    reviewer = Ed25519PrivateKey.generate()
    directory = TemporaryDirectory(prefix="maverick-test-publisher-")
    test.addCleanup(directory.cleanup)
    policy_path = Path(directory.name) / "trust.json"
    def principal(key, ref):
        return {"principal_ref": ref, "public_key": base64.b64encode(
            key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()}
    policy_path.write_text(json.dumps({
        "schema": "maverick-certification-publisher-trust.v1",
        "collectors": {signed.signer_key_id: principal(private_key, "7" * 64)},
        "reviewers": {"test-reviewer": principal(reviewer, "6" * 64)},
    }))
    policy_path.chmod(0o600)
    refs = verify_retained_run(signed.run, fixture_artifact_store())
    payload = dict(signed_run_digest=signed_artifact_digest(signed),
                   artifacts_digest=artifact_manifest_digest(refs),
                   reviewed_at=datetime.now(UTC).isoformat())
    review = CertificationReview(
        signer_key_id="test-reviewer", **payload,
        signature=base64.b64encode(reviewer.sign(review_payload(**payload))).decode(),
    )
    return CertificationPublicationAuthority(
        trust_policy_path=policy_path, evidence_store=fixture_artifact_store(),
    ), review
