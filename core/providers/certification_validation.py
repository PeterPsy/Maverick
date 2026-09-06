"""Complete protocol and natural evidence checks used before every signature."""

from datetime import UTC, datetime
import re

from core.providers.certification_records import CertificationRunResult
from core.providers.certification_manifests import get_certification_manifest
from core.providers.certification_target import (
    api_certification_resource_limits, builtin_api_certification_profile,
    builtin_api_certification_target, builtin_api_reasoning_efforts,
)
from core.providers.certification_behavior import validate_behavioral_evidence
from core.providers.certification_live_receipt import validate_live_probe_receipt
from core.providers.certification_summary import certification_result_summary
from core.providers.certification_fixture_receipt import validate_fixture_receipt
from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


def validate_completed_run(run: CertificationRunResult) -> None:
    _require_aware(run.started_at)
    _require_aware(run.completed_at)
    if run.outcome != "passed" or run.completed_at < run.started_at:
        raise CapabilityCertificateError("certification_run_not_passed")
    if not run.test_run_id.startswith("run:"):
        raise CapabilityCertificateError("certification_test_run_id_invalid")
    if not isinstance(run.source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", run.source_commit):
        raise CapabilityCertificateError("certification_source_commit_missing")
    if not isinstance(run.collection_nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", run.collection_nonce):
        raise CapabilityCertificateError("certification_live_receipt_invalid")
    _required(run.matrix_revision, "certification_matrix_revision_missing")
    for value in (
        run.adapter_artifact_digest,
        run.artifact_bundle_digest,
        run.matrix_digest,
        run.result_summary_digest,
        run.manifest_digest,
        run.tcb_structure_digest,
        run.tcb_live_digest,
        run.target_digest,
    ):
        _sha256(value)
    if not run.evidence_refs:
        raise CapabilityCertificateError("certificate_evidence_ref_invalid")
    if (not isinstance(run.step_results, tuple)
            or any(not isinstance(item, dict) for item in run.step_results)):
        raise CapabilityCertificateError("certification_step_manifest_mismatch")
    if {str(item.get("kind")) for item in run.step_results} != {
        "fixture_contract",
        "live_probe",
    }:
        raise CapabilityCertificateError("certification_required_steps_missing")
    manifest = get_certification_manifest(run.suite_id, run.suite_version)
    if run.target_digest != builtin_api_certification_target(manifest.provider_id):
        raise CapabilityCertificateError("certification_target_mismatch")
    if run.manifest_digest != manifest.digest:
        raise CapabilityCertificateError("certification_manifest_mismatch")
    if (
        run.tcb_manifest_id != manifest.tcb_manifest_id
        or run.tcb_manifest_version != manifest.tcb_manifest_version
        or run.tcb_structure_digest != manifest.tcb_structure_digest
        or run.artifact_bundle_digest != run.tcb_live_digest
    ):
        raise CapabilityCertificateError("certificate_tcb_identity_mismatch")
    expected_steps = tuple(
        (step.step_id, step.kind, canonical_digest(step.command))
        for step in manifest.steps
    )
    actual_steps = tuple(
        (item.get("step_id"), item.get("kind"), item.get("command_digest"))
        for item in run.step_results
    )
    if actual_steps != expected_steps:
        raise CapabilityCertificateError("certification_step_manifest_mismatch")
    if any(item.get("outcome") != "passed" or item.get("exit_code") != 0 for item in run.step_results):
        raise CapabilityCertificateError("certification_run_not_passed")
    for step in run.step_results:
        fields = {"step_id", "kind", "command_digest", "exit_code", "stdout_digest", "stderr_digest", "outcome"}
        if step["kind"] == "live_probe":
            fields.add("live_receipt")
        else:
            fields.add("fixture_receipt")
            validate_fixture_receipt(step.get("fixture_receipt"))
        if set(step) != fields or type(step["exit_code"]) is not int:
            raise CapabilityCertificateError("certification_step_manifest_mismatch")
        for key in ("stdout_digest", "stderr_digest"):
            _sha256(step[key])
        if step["kind"] == "live_probe":
            validate_live_probe_receipt(
                step.get("live_receipt"), provider_id=manifest.provider_id,
                target_digest=run.target_digest, run_nonce=run.collection_nonce,
            )
    expected_summary = canonical_digest(certification_result_summary(run))
    if run.result_summary_digest != expected_summary:
        raise CapabilityCertificateError("certification_result_summary_mismatch")
    if len(set(run.evidence_refs)) != len(run.evidence_refs) or any(
        not isinstance(ref, str) or not re.fullmatch(r"platform-evidence:[A-Za-z0-9:_-]{1,160}", ref)
        for ref in run.evidence_refs
    ):
        raise CapabilityCertificateError("certificate_evidence_ref_invalid")
    if run.behavioral_evidence is None:
        raise CapabilityCertificateError("certification_behavior_required")
    if f"platform-evidence:sha256:{canonical_digest(run.behavioral_evidence)}" not in run.evidence_refs:
        raise CapabilityCertificateError("certification_behavior_reference_missing")
    validate_behavioral_evidence(
        run.behavioral_evidence, target_digest=run.target_digest,
        source_commit=run.source_commit, tcb_live_digest=run.tcb_live_digest,
        not_before=run.completed_at, now=datetime.now(tz=UTC),
        reasoning_efforts=builtin_api_reasoning_efforts(manifest.provider_id),
        resource_limits=api_certification_resource_limits(builtin_api_certification_profile(manifest.provider_id)),
    )


def _sha256(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise CapabilityCertificateError("certification_digest_invalid")
    return normalized


def _required(value: str, reason: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CapabilityCertificateError(reason)
    return normalized


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CapabilityCertificateError("certification_time_invalid")
