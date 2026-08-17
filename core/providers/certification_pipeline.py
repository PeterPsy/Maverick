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
    evidence_refs: tuple[str, ...]
    started_at: datetime
    completed_at: datetime
    outcome: str


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
    command: Sequence[str],
    cwd: Path,
    suite_id: str,
    suite_version: str,
    adapter_artifact_digest: str,
    artifact_paths: Sequence[Path],
    matrix_path: Path,
    matrix_revision: str,
    evidence_refs: tuple[str, ...],
    started_at: datetime | None = None,
    environment: Mapping[str, str] | None = None,
) -> CertificationRunResult:
    """Run the authoritative suite and return evidence only after a clean exit."""
    if not command:
        raise CapabilityCertificateError("certification_command_missing")
    start = started_at or datetime.now(tz=UTC)
    _require_aware(start)
    source_commit = _git_commit(cwd)
    matrix_bytes = matrix_path.resolve().read_bytes()
    bundle_digest = _artifact_bundle_digest(cwd, artifact_paths)
    completed = subprocess.run(
        tuple(command),
        cwd=cwd,
        env=dict(environment) if environment is not None else None,
        capture_output=True,
        check=False,
    )
    end = datetime.now(tz=UTC)
    summary = {
        "command": tuple(command),
        "exit_code": completed.returncode,
        "stdout_digest": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_digest": hashlib.sha256(completed.stderr).hexdigest(),
    }
    if completed.returncode != 0:
        raise CapabilityCertificateError("certification_suite_failed")
    test_run_id = canonical_digest(
        {
            "suite_id": suite_id,
            "suite_version": suite_version,
            "source_commit": source_commit,
            "adapter_artifact_digest": adapter_artifact_digest,
            "artifact_bundle_digest": bundle_digest,
            "matrix_revision": matrix_revision,
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
        matrix_revision=_required(matrix_revision, "certification_matrix_revision_missing"),
        matrix_digest=hashlib.sha256(matrix_bytes).hexdigest(),
        result_summary_digest=canonical_digest(summary),
        evidence_refs=evidence_refs,
        started_at=start,
        completed_at=end,
        outcome="passed",
    )


def sign_certification_run(
    run: CertificationRunResult,
    *,
    signer_key_id: str,
    private_key: Ed25519PrivateKey,
) -> SignedCertificationRun:
    validate_completed_run(run)
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
) -> CertificationRunResult:
    validate_completed_run(signed.run)
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
    ):
        _sha256(value)
    if not run.evidence_refs:
        raise CapabilityCertificateError("certificate_evidence_ref_invalid")


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
