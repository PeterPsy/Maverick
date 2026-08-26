"""Execute, sign, verify, and persist agentic certification runs."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

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
from core.providers.errors import CapabilityCertificateError
from core.runtime.execution_binding import canonical_digest


@dataclass(frozen=True)
class CertificationRunResult:
    """Immutable result of one completed certification suite execution."""

    suite_id: str
    suite_version: str
    test_run_id: str
    source_commit: str
    adapter_artifact_digest: str
    artifact_bundle_digest: str
    matrix_revision: str
    matrix_digest: str
    result_summary_digest: str
    manifest_digest: str
    step_results: tuple[dict[str, object], ...]
    evidence_refs: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    outcome: str
    tcb_manifest_id: str = ""
    tcb_manifest_version: str = ""
    tcb_structure_digest: str = ""
    tcb_live_digest: str = ""


@dataclass(frozen=True)
class SignedCertificationRun:
    run: CertificationRunResult
    signer_key_id: str
    signature: str


def signed_run_to_json(signed: SignedCertificationRun) -> str:
    payload = {
        "run": {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in signed.run.__dict__.items()
        },
        "signer_key_id": signed.signer_key_id,
        "signature": signed.signature,
    }
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def signed_run_from_json(value: str) -> SignedCertificationRun:
    try:
        payload = json.loads(value)
        run_payload = dict(payload["run"])
        run_payload["evidence_refs"] = tuple(run_payload["evidence_refs"])
        run_payload["step_results"] = tuple(run_payload["step_results"])
        for field in (
            "tcb_manifest_id",
            "tcb_manifest_version",
            "tcb_structure_digest",
            "tcb_live_digest",
        ):
            run_payload.setdefault(field, "")
        for field in ("started_at", "completed_at"):
            run_payload[field] = datetime.fromisoformat(run_payload[field])
        return SignedCertificationRun(
            run=CertificationRunResult(**run_payload),
            signer_key_id=str(payload["signer_key_id"]),
            signature=str(payload["signature"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CapabilityCertificateError("certification_artifact_invalid") from error


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
    step_results: list[dict[str, object]] = []
    for step in selected_steps:
        completed = subprocess.run(
            step.command, cwd=cwd,
            env=dict(environment) if environment is not None else None,
            capture_output=True, check=False,
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
        if completed.returncode != 0:
            raise CapabilityCertificateError(f"certification_step_failed:{step.step_id}")
    _require_clean_checkout(cwd)
    if _git_commit(cwd) != source_commit:
        raise CapabilityCertificateError("certification_source_commit_changed")
    final_tcb_identity = certified_tcb_identity(cwd)
    if final_tcb_identity != tcb_identity:
        raise CapabilityCertificateError("certificate_tcb_drift")
    end = datetime.now(tz=UTC)
    summary = {
        "manifest_digest": manifest.digest,
        "tcb_manifest_id": tcb_identity.manifest_id,
        "tcb_manifest_version": tcb_identity.manifest_version,
        "tcb_structure_digest": tcb_identity.structure_digest,
        "tcb_live_digest": tcb_identity.live_digest,
        "steps": tuple(step_results),
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
    )


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


def validate_completed_run(run: CertificationRunResult) -> None:
    if run.outcome != "passed" or run.completed_at < run.started_at:
        raise CapabilityCertificateError("certification_run_not_passed")
    _require_aware(run.started_at)
    _require_aware(run.completed_at)
    if not run.test_run_id.startswith("run:"):
        raise CapabilityCertificateError("certification_test_run_id_invalid")
    _required(run.source_commit, "certification_source_commit_missing")
    _required(run.matrix_revision, "certification_matrix_revision_missing")
    for value in (
        run.adapter_artifact_digest,
        run.artifact_bundle_digest,
        run.matrix_digest,
        run.result_summary_digest,
        run.manifest_digest,
        run.tcb_structure_digest,
        run.tcb_live_digest,
    ):
        _sha256(value)
    if not run.evidence_refs:
        raise CapabilityCertificateError("certificate_evidence_ref_invalid")
    if {str(item.get("kind")) for item in run.step_results} != {
        "fixture_contract",
        "live_probe",
    }:
        raise CapabilityCertificateError("certification_required_steps_missing")
    manifest = get_certification_manifest(run.suite_id, run.suite_version)
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
    expected_summary = canonical_digest({
        "manifest_digest": run.manifest_digest,
        "tcb_manifest_id": run.tcb_manifest_id,
        "tcb_manifest_version": run.tcb_manifest_version,
        "tcb_structure_digest": run.tcb_structure_digest,
        "tcb_live_digest": run.tcb_live_digest,
        "steps": run.step_results,
    })
    if run.result_summary_digest != expected_summary:
        raise CapabilityCertificateError("certification_result_summary_mismatch")
    if len(set(run.evidence_refs)) != len(run.evidence_refs) or any(
        not str(ref).startswith("platform-evidence:") for ref in run.evidence_refs
    ):
        raise CapabilityCertificateError("certificate_evidence_ref_invalid")


def validate_run_against_manifest(
    run: CertificationRunResult,
    *,
    cwd: Path,
    deployed_source_commit: str | None = None,
) -> CertificationSuiteManifest:
    """Recompute publisher-owned identities instead of trusting signed CLI inputs."""
    manifest = get_certification_manifest(run.suite_id, run.suite_version)
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


def _artifact_bundle_digest(cwd: Path, paths: Sequence[Path]) -> str:
    if not paths:
        raise CapabilityCertificateError("certification_artifact_bundle_empty")
    digest = hashlib.sha256()
    for item in sorted((path.resolve() for path in paths), key=str):
        try:
            relative = item.relative_to(cwd.resolve())
        except ValueError as error:
            raise CapabilityCertificateError("certification_artifact_outside_source") from error
        if not item.is_file():
            raise CapabilityCertificateError("certification_artifact_missing")
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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
    if value.tzinfo is None or value.utcoffset() is None:
        raise CapabilityCertificateError("certification_time_invalid")
