"""Immutable certification collection records and bounded JSON serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from core.providers.certification_live_receipt import decode_certification_json
from core.providers.errors import CapabilityCertificateError


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
    target_digest: str = ""
    collection_nonce: str = ""
    behavioral_evidence: dict[str, object] | None = None

    @property
    def certification_completed_at(self) -> datetime:
        """Natural conformance completes after the protocol collection."""
        if self.behavioral_evidence is None:
            return self.completed_at
        return datetime.fromisoformat(self.behavioral_evidence["completed_at"])


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
        payload = decode_certification_json(value)
        if not isinstance(payload, dict) or set(payload) != {"run", "signer_key_id", "signature"}:
            raise ValueError
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


def collection_to_json(run: CertificationRunResult) -> str:
    payload = json.loads(signed_run_to_json(SignedCertificationRun(run, "", "")))["run"]
    return json.dumps({"schema": "maverick-certification-collection.v1", "run": payload}, sort_keys=True, indent=2) + "\n"


def collection_from_json(value: str | bytes) -> CertificationRunResult:
    payload = decode_certification_json(value)
    if (not isinstance(payload, dict) or set(payload) != {"schema", "run"}
            or payload["schema"] != "maverick-certification-collection.v1"):
        raise CapabilityCertificateError("certification_collection_invalid")
    return signed_run_from_json(json.dumps({"run": payload["run"], "signer_key_id": "", "signature": ""})).run
