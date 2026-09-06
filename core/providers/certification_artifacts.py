"""Retained certification bytes, distinct from signed claims about those bytes."""

import hashlib
import json
from typing import Protocol

from core.providers.certification_fixture_receipt import fixture_receipt
from core.providers.certification_live_receipt import decode_certification_json, validate_live_probe_receipt
from core.providers.certification_manifests import get_certification_manifest
from core.providers.errors import CapabilityCertificateError
from core.providers.evidence_store import EVIDENCE_REF_PREFIX
from core.runtime.execution_binding import canonical_digest


class CertificationArtifactStore(Protocol):
    def put(self, content: bytes, *, expected_digest: str | None = None) -> str: ...
    def get(self, evidence_ref: str) -> bytes: ...


def canonical_artifact(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def retained_run_references(run) -> tuple[str, ...]:
    """Require the report, every observation source and both step output streams."""
    report = run.behavioral_evidence
    if report is None:
        raise CapabilityCertificateError("certification_behavior_required")
    refs = set(run.evidence_refs)
    refs.add(EVIDENCE_REF_PREFIX + canonical_digest(report))
    for observation in report["observations"]:
        for field in ("prompt_digest", "trace_digest", "semantic_source_digest",
                      "semantic_projection_digest", "effect_digest"):
            refs.add(EVIDENCE_REF_PREFIX + observation[field])
    for step in run.step_results:
        refs.update(EVIDENCE_REF_PREFIX + step[field] for field in ("stdout_digest", "stderr_digest"))
    return tuple(sorted(refs))


def verify_retained_run(run, store: CertificationArtifactStore) -> tuple[str, ...]:
    """Read through digest verification, not an existence check or caller receipt."""
    refs = retained_run_references(run)
    for ref in refs:
        content = store.get(ref)
        if ref != EVIDENCE_REF_PREFIX + hashlib.sha256(content).hexdigest():
            raise CapabilityCertificateError("certificate_evidence_blob_corrupt")
    report_ref = EVIDENCE_REF_PREFIX + canonical_digest(run.behavioral_evidence)
    if store.get(report_ref) != canonical_artifact(run.behavioral_evidence):
        raise CapabilityCertificateError("certification_behavior_artifact_mismatch")
    # The publisher checks observed output bytes too, not only the collector's
    # signed assertion that those bytes contained successful step receipts.
    manifest = get_certification_manifest(run.suite_id, run.suite_version)
    for step in run.step_results:
        if step["kind"] == "fixture_contract":
            observed = fixture_receipt(store.get(EVIDENCE_REF_PREFIX + step["stderr_digest"]))
            declared = step["fixture_receipt"]
        elif step["kind"] == "live_probe":
            observed = validate_live_probe_receipt(
                decode_certification_json(store.get(EVIDENCE_REF_PREFIX + step["stdout_digest"]), max_bytes=16_384),
                provider_id=manifest.provider_id, target_digest=run.target_digest, run_nonce=run.collection_nonce,
            )
            declared = step["live_receipt"]
        else:
            raise CapabilityCertificateError("certification_step_manifest_mismatch")
        if observed != declared:
            raise CapabilityCertificateError("certification_artifact_receipt_mismatch")
    return refs
