"""Retained certification bytes, distinct from signed claims about those bytes."""

import hashlib
import json
from typing import Protocol

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
    return refs
