"""Canonical summary binding protocol collection to independently observed behavior."""

from core.runtime.execution_binding import canonical_digest


def certification_result_summary(run) -> dict:
    return {
        "manifest_digest": run.manifest_digest,
        "target_digest": run.target_digest,
        "collection_nonce": run.collection_nonce,
        "tcb_manifest_id": run.tcb_manifest_id,
        "tcb_manifest_version": run.tcb_manifest_version,
        "tcb_structure_digest": run.tcb_structure_digest,
        "tcb_live_digest": run.tcb_live_digest,
        "steps": run.step_results,
        "behavioral_evidence_digest": (
            canonical_digest(run.behavioral_evidence) if run.behavioral_evidence is not None else None
        ),
    }
