"""Execute, sign, verify, and persist agentic certification runs."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping, Sequence
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from core.providers.certification_manifests import (
    CertificationStepManifest,
    CertificationSuiteManifest,
    get_certification_manifest,
    resolve_manifest_path,
)
from core.providers.certified_execution_tcb import (
    certified_tcb_identity,
    validate_remote_tcb_identity,
)
from core.providers.certification_records import (
    CertificationRunResult, SignedCertificationRun, signed_run_from_json, signed_run_to_json,
)
from core.providers.errors import CapabilityCertificateError
from core.providers.certification_target import builtin_api_certification_target
from core.providers.certification_validation import (
    validate_completed_run, _sha256, _required, _require_aware,
)
from core.providers.certification_summary import certification_result_summary
from core.providers.certification_fixture_receipt import fixture_receipt
from core.providers.certification_artifacts import CertificationArtifactStore, canonical_artifact
from core.providers.certification_live_receipt import (
    decode_certification_json, validate_live_probe_receipt,
)
from core.runtime.execution_binding import canonical_digest


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    try:
        key = load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as error:
        raise CapabilityCertificateError("certification_private_key_invalid") from error
    if not isinstance(key, Ed25519PrivateKey):
        raise CapabilityCertificateError("certification_private_key_invalid")
    return key


def execute_certification_suite(
    *,
    cwd: Path,
    suite_id: str,
    suite_version: str,
    adapter_artifact_digest: str,
    evidence_refs: tuple[str, ...],
    started_at: datetime | None = None,
    environment: Mapping[str, str] | None = None,
    step_kinds: Sequence[str] | None = None,
    evidence_store: CertificationArtifactStore | None = None,
) -> CertificationRunResult:
    """Run selected code-owned steps; only a complete run is certificate evidence."""
    manifest = get_certification_manifest(suite_id, suite_version)
    selected_steps = _selected_manifest_steps(manifest, step_kinds=step_kinds)
    _require_clean_checkout(cwd)
    start = started_at or datetime.now(tz=UTC)
    _require_aware(start)
    source_commit = _git_commit(cwd)
    tcb_identity = certified_tcb_identity(cwd)
    matrix_bytes = resolve_manifest_path(cwd, manifest.matrix_path).read_bytes()
    bundle_digest = tcb_identity.live_digest
    target_digest = builtin_api_certification_target(manifest.provider_id)
    collection_nonce = uuid4().hex
    child_environment = dict(os.environ if environment is None else environment)
    child_environment["MAVERICK_CERTIFICATION_RUN_NONCE"] = collection_nonce
    step_results: list[dict[str, object]] = []
    for step in selected_steps:
        completed = subprocess.run(
            step.command, cwd=cwd,
            env=child_environment,
            capture_output=True, check=False,
            timeout=1_800 if step.kind == "fixture_contract" else 900,
        )
        step_results.append({
            "step_id": step.step_id,
            "kind": step.kind,
            "command_digest": canonical_digest(step.command),
            "exit_code": completed.returncode,
            "stdout_digest": hashlib.sha256(completed.stdout).hexdigest(),
            "stderr_digest": hashlib.sha256(completed.stderr).hexdigest(),
            "outcome": "passed" if completed.returncode == 0 else "failed",
        })
        if evidence_store is not None:
            for content in (completed.stdout, completed.stderr):
                evidence_store.put(content)
        if completed.returncode != 0:
            raise CapabilityCertificateError(f"certification_step_failed:{step.step_id}")
        if step.kind == "fixture_contract":
            step_results[-1]["fixture_receipt"] = fixture_receipt(completed.stderr)
        if step.kind == "live_probe":
            step_results[-1]["live_receipt"] = validate_live_probe_receipt(
                decode_certification_json(completed.stdout, max_bytes=16_384),
                provider_id=manifest.provider_id, target_digest=target_digest,
                run_nonce=collection_nonce,
            )
    _require_clean_checkout(cwd)
    if _git_commit(cwd) != source_commit:
        raise CapabilityCertificateError("certification_source_commit_changed")
    final_tcb_identity = certified_tcb_identity(cwd)
    if final_tcb_identity != tcb_identity:
        raise CapabilityCertificateError("certificate_tcb_drift")
    end = datetime.now(tz=UTC)
    summary = {
        "manifest_digest": manifest.digest,
        "target_digest": target_digest,
        "collection_nonce": collection_nonce,
        "tcb_manifest_id": tcb_identity.manifest_id,
        "tcb_manifest_version": tcb_identity.manifest_version,
        "tcb_structure_digest": tcb_identity.structure_digest,
        "tcb_live_digest": tcb_identity.live_digest,
        "steps": tuple(step_results),
        "behavioral_evidence_digest": None,
    }
    test_run_id = canonical_digest(
        {
            "suite_id": suite_id,
            "suite_version": suite_version,
            "source_commit": source_commit,
            "adapter_artifact_digest": adapter_artifact_digest,
            "artifact_bundle_digest": bundle_digest,
            "tcb_identity": tcb_identity,
            "matrix_revision": manifest.matrix_revision,
            "matrix_digest": hashlib.sha256(matrix_bytes).hexdigest(),
            "started_at": start,
            "completed_at": end,
            "result_summary": summary,
        }
    )
    return CertificationRunResult(
        suite_id=suite_id,
        suite_version=suite_version,
        test_run_id=f"run:{test_run_id}",
        source_commit=source_commit,
        adapter_artifact_digest=_sha256(adapter_artifact_digest),
        artifact_bundle_digest=bundle_digest,
        matrix_revision=manifest.matrix_revision,
        matrix_digest=hashlib.sha256(matrix_bytes).hexdigest(),
        result_summary_digest=canonical_digest(summary),
        manifest_digest=manifest.digest,
        step_results=tuple(step_results),
        evidence_refs=evidence_refs,
        started_at=start,
        completed_at=end,
        outcome="passed",
        tcb_manifest_id=tcb_identity.manifest_id,
        tcb_manifest_version=tcb_identity.manifest_version,
        tcb_structure_digest=tcb_identity.structure_digest,
        tcb_live_digest=tcb_identity.live_digest,
        target_digest=target_digest,
        collection_nonce=collection_nonce,
    )


def attach_behavioral_evidence(
    run: CertificationRunResult, report: object, *, cwd: Path,
    evidence_store: CertificationArtifactStore,
) -> CertificationRunResult:
    """Seal an independent, later natural run into collected protocol evidence.

    This does not run a model, invent observations, approve release, or sign.
    The trusted signer remains responsible for reviewing the actual traces.
    """
    validate_run_against_manifest(run, cwd=cwd)
    if run.behavioral_evidence is not None:
        raise CapabilityCertificateError("certification_behavior_already_attached")
    # Copy before validation so a caller cannot mutate a previously checked report.
    try:
        snapshot = decode_certification_json(json.dumps(report, allow_nan=False))
    except (ValueError, TypeError) as error:
        raise CapabilityCertificateError("certification_behavior_shape_invalid") from error
    evidence_ref = f"platform-evidence:sha256:{canonical_digest(snapshot)}"
    candidate = replace(run, behavioral_evidence=snapshot, evidence_refs=(*run.evidence_refs, evidence_ref))
    candidate = replace(candidate, result_summary_digest=canonical_digest(certification_result_summary(candidate)))
    validate_completed_run(candidate)
    # A reference is emitted only after actual durable retention. Publication
    # separately reads and verifies the complete trace/source/effect closure.
    stored_ref = evidence_store.put(canonical_artifact(snapshot), expected_digest=canonical_digest(snapshot))
    if stored_ref != evidence_ref:
        raise CapabilityCertificateError("certification_behavior_artifact_mismatch")
    return candidate


def sign_certification_run(
    run: CertificationRunResult,
    *,
    signer_key_id: str,
    private_key: Ed25519PrivateKey,
    cwd: Path | None = None,
) -> SignedCertificationRun:
    validate_completed_run(run)
    _validate_run_tcb(run, cwd=cwd)
    key_id = _required(signer_key_id, "certification_signer_key_missing")
    signature = private_key.sign(_run_payload(run))
    return SignedCertificationRun(
        run=run,
        signer_key_id=key_id,
        signature=base64.b64encode(signature).decode("ascii"),
    )


def verify_certification_run(
    signed: SignedCertificationRun,
    *,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    cwd: Path | None = None,
) -> CertificationRunResult:
    validate_completed_run(signed.run)
    _validate_run_tcb(signed.run, cwd=cwd)
    public_key = trusted_keys.get(signed.signer_key_id)
    if public_key is None:
        raise CapabilityCertificateError("certification_signer_untrusted")
    try:
        signature = base64.b64decode(signed.signature, validate=True)
        public_key.verify(signature, _run_payload(signed.run))
    except (InvalidSignature, ValueError) as error:
        raise CapabilityCertificateError("certification_signature_invalid") from error
    return signed.run


def validate_run_against_manifest(
    run: CertificationRunResult,
    *,
    cwd: Path,
    deployed_source_commit: str | None = None,
) -> CertificationSuiteManifest:
    """Recompute publisher-owned identities instead of trusting signed CLI inputs."""
    manifest = get_certification_manifest(run.suite_id, run.suite_version)
    if run.target_digest != builtin_api_certification_target(manifest.provider_id):
        raise CapabilityCertificateError("certification_target_mismatch")
    if run.manifest_digest != manifest.digest:
        raise CapabilityCertificateError("certification_manifest_mismatch")
    current_tcb = validate_remote_tcb_identity(
        manifest_id=run.tcb_manifest_id,
        manifest_version=run.tcb_manifest_version,
        structure_digest=run.tcb_structure_digest,
        live_digest=run.tcb_live_digest,
        root=cwd,
    )
    if run.artifact_bundle_digest != current_tcb.live_digest:
        raise CapabilityCertificateError("certification_artifact_bundle_mismatch")
    expected_steps = tuple(
        (step.step_id, step.kind, canonical_digest(step.command)) for step in manifest.steps
    )
    actual_steps = tuple(
        (item.get("step_id"), item.get("kind"), item.get("command_digest"))
        for item in run.step_results
    )
    if actual_steps != expected_steps:
        raise CapabilityCertificateError("certification_step_manifest_mismatch")
    matrix = resolve_manifest_path(cwd, manifest.matrix_path)
    if run.matrix_revision != manifest.matrix_revision:
        raise CapabilityCertificateError("certification_matrix_revision_mismatch")
    if run.matrix_digest != hashlib.sha256(matrix.read_bytes()).hexdigest():
        raise CapabilityCertificateError("certification_matrix_digest_mismatch")
    deployed = deployed_source_commit or _git_commit(cwd)
    if run.source_commit != deployed:
        raise CapabilityCertificateError("certification_source_commit_mismatch")
    return manifest


def _validate_run_tcb(
    run: CertificationRunResult,
    *,
    cwd: Path | None,
) -> None:
    validate_remote_tcb_identity(
        manifest_id=run.tcb_manifest_id,
        manifest_version=run.tcb_manifest_version,
        structure_digest=run.tcb_structure_digest,
        live_digest=run.tcb_live_digest,
        root=cwd,
    )


def _selected_manifest_steps(
    manifest: CertificationSuiteManifest,
    *,
    step_kinds: Sequence[str] | None,
) -> tuple[CertificationStepManifest, ...]:
    if step_kinds is None:
        return manifest.steps
    normalized = tuple(str(kind or "").strip() for kind in step_kinds)
    if (
        not normalized
        or any(not kind for kind in normalized)
        or len(set(normalized)) != len(normalized)
    ):
        raise CapabilityCertificateError("certification_step_selection_invalid")
    available = {step.kind for step in manifest.steps}
    if any(kind not in available for kind in normalized):
        raise CapabilityCertificateError("certification_step_selection_invalid")
    return tuple(step for step in manifest.steps if step.kind in normalized)


def _git_commit(cwd: Path) -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CapabilityCertificateError("certification_source_commit_unavailable")
    return _required(result.stdout, "certification_source_commit_unavailable")


def _require_clean_checkout(cwd: Path) -> None:
    result = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=normal"),
        cwd=cwd, capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise CapabilityCertificateError("certification_source_status_unavailable")
    if result.stdout.strip():
        raise CapabilityCertificateError("certification_source_checkout_dirty")


def _run_payload(run: CertificationRunResult) -> bytes:
    payload = {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in run.__dict__.items()
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")




__all__ = [
    "CertificationRunResult", "SignedCertificationRun", "signed_run_from_json", "signed_run_to_json",
    "execute_certification_suite", "attach_behavioral_evidence", "sign_certification_run",
    "verify_certification_run", "validate_completed_run", "validate_run_against_manifest",
    "load_ed25519_private_key",
]
