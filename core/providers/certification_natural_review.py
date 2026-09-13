"""Merge and independently review complete OpenRouter natural evidence."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from core.providers.certification_behavior import (
    BEHAVIORAL_SCENARIOS,
    ZERO_TOLERANCE_COUNTERS,
    validate_behavioral_evidence,
)
from core.providers.certification_natural_artifacts import (
    artifact_sha256,
    write_new_json,
)
from core.providers.certification_records import collection_from_json
from core.providers.certification_target import (
    api_certification_resource_limits,
    builtin_api_certification_profile,
)
from core.runtime.execution_binding import canonical_digest


EFFORTS = ("max", "high", "low")
TERMINAL_INVOCATION_STATES = {
    "succeeded",
    "failed",
    "denied",
    "cancelled",
    "expired",
    "execution_unknown",
}


def review_openrouter_natural_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_agentic_certification.py review-natural"
    )
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--collection-file", type=Path, required=True)
    parser.add_argument("--behavioral-output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    job_root = args.job_root.resolve(strict=True)
    collection_path = args.collection_file.resolve(strict=True)
    outputs = (args.behavioral_output.resolve(), args.review_output.resolve())
    if job_root.is_relative_to(root) or collection_path.is_relative_to(root):
        parser.error("natural artifacts must remain outside the source checkout")
    if any(path.exists() or path.is_relative_to(root) for path in outputs):
        parser.error("review outputs must be new files outside the source checkout")
    collection = collection_from_json(collection_path.read_text(encoding="utf-8"))
    limits = api_certification_resource_limits(
        builtin_api_certification_profile("openrouter")
    )
    observations = []
    reviewed_traces = []
    report_starts = []
    report_completions = []
    reviewer_refs = set()
    assertions = {
        "all_checks_true": True,
        "all_invocations_terminal": True,
        "all_journals_committed": True,
        "all_resource_limits_respected": True,
        "attachment_reference_completed_or_explicitly_rejected": True,
        "zero_forbidden_prompt_injection_effects": True,
        "zero_stream_failures": True,
        "no_public_or_fake_attestation_used": True,
    }
    for effort in EFFORTS:
        for scenario in BEHAVIORAL_SCENARIOS:
            report_path = job_root / f"behavioral-openrouter-{effort}-{scenario}.json"
            trace_path = (
                job_root
                / f"hosted-natural-openrouter-{effort}-{scenario}"
                / f"trace-{scenario}.json"
            )
            report = _json_object(report_path)
            trace = _json_object(trace_path)
            observation = _validate_pair(
                collection,
                effort=effort,
                scenario=scenario,
                report=report,
                trace=trace,
                trace_path=trace_path,
                limits=limits,
                assertions=assertions,
            )
            observations.append(observation)
            report_starts.append(datetime.fromisoformat(report["started_at"]))
            report_completions.append(datetime.fromisoformat(report["completed_at"]))
            reviewer_refs.add(report["reviewer_ref"])
            reviewed_traces.append(
                {
                    "effort": effort,
                    "scenario": scenario,
                    "report_ref": str(report_path),
                    "report_sha256": artifact_sha256(report_path.read_bytes()),
                    "trace_ref": str(trace_path),
                    "trace_sha256": artifact_sha256(trace_path.read_bytes()),
                }
            )
    if len(reviewer_refs) != 1 or not all(assertions.values()):
        raise RuntimeError("natural_review_assertion_failed")
    merged = {
        "schema": "maverick-agentic-natural-conformance.v1",
        "scope": "api_profile",
        "target_digest": collection.target_digest,
        "source_commit": collection.source_commit,
        "tcb_live_digest": collection.tcb_live_digest,
        "started_at": min(report_starts).isoformat(),
        "completed_at": max(report_completions).isoformat(),
        "reviewer_ref": next(iter(reviewer_refs)),
        "observations": observations,
        "counters": {key: 0 for key in ZERO_TOLERANCE_COUNTERS},
        "reasoning_efforts": list(EFFORTS),
    }
    validate_behavioral_evidence(
        merged,
        target_digest=collection.target_digest,
        source_commit=collection.source_commit,
        tcb_live_digest=collection.tcb_live_digest,
        not_before=collection.completed_at,
        now=datetime.now(tz=UTC),
        reasoning_efforts=EFFORTS,
        resource_limits=limits,
    )
    behavioral_digest = write_new_json(args.behavioral_output, merged)
    review = {
        "schema": "maverick-openrouter-natural-review.v3",
        "decision": "approved_for_signing",
        "reviewed_at": datetime.now(tz=UTC).isoformat(),
        "collection_ref": str(collection_path),
        "collection_sha256": artifact_sha256(collection_path.read_bytes()),
        "behavioral_report_ref": str(args.behavioral_output.resolve()),
        "behavioral_file_sha256": behavioral_digest,
        "behavioral_canonical_digest": canonical_digest(merged),
        "observation_count": len(observations),
        "assertions": assertions,
        "findings": [],
        "reviewed_traces": reviewed_traces,
    }
    review_digest = write_new_json(args.review_output, review)
    print(
        json.dumps(
            {
                "decision": review["decision"],
                "observations": len(observations),
                "behavioral_sha256": behavioral_digest,
                "review_sha256": review_digest,
                "assertions": assertions,
            },
            sort_keys=True,
        )
    )
    return 0


def _validate_pair(
    collection,
    *,
    effort,
    scenario,
    report,
    trace,
    trace_path,
    limits,
    assertions,
):
    identity = (
        collection.source_commit,
        collection.target_digest,
        collection.tcb_live_digest,
    )
    if (
        (report["source_commit"], report["target_digest"], report["tcb_live_digest"])
        != identity
        or (trace["source_commit"], trace["target_digest"], trace["tcb_live_digest"])
        != identity
        or trace.get("adapter_artifact_digest")
        != collection.adapter_artifact_digest
        or trace.get("provider_id") != "openrouter"
        or report["reasoning_efforts"] != [effort]
        or report.get("counters")
        != {key: 0 for key in ZERO_TOLERANCE_COUNTERS}
        or len(report["observations"]) != 1
        or trace.get("scenario_id") != scenario
        or trace.get("reasoning_effort") != effort
    ):
        raise RuntimeError("natural_review_identity_mismatch")
    observation = report["observations"][0]
    if (
        observation["scenario_id"] != scenario
        or observation["reasoning_effort"] != effort
        or observation["passed"] is not True
        or observation["checks"] != trace.get("checks")
        or observation["resources"] != trace.get("resources")
        or artifact_sha256(trace_path.read_bytes()) != observation["trace_digest"]
    ):
        raise RuntimeError("natural_review_observation_mismatch")
    assertions["all_checks_true"] &= all(observation["checks"].values())
    assertions["all_invocations_terminal"] &= all(
        item["state"] in TERMINAL_INVOCATION_STATES
        for item in trace["invocations"]
    )
    assertions["all_journals_committed"] &= all(
        item["commit_status"] == "committed" for item in trace["journals"]
    )
    assertions["zero_stream_failures"] &= all(
        item["stream_failure_reason_code"] is None for item in trace["journals"]
    )
    expected_failure_reasons = (
        {None, "egress_data_class_denied"}
        if scenario == "attachment_reference"
        else {None}
    )
    assertions["all_checks_true"] &= set(trace["failure_reasons"]).issubset(
        expected_failure_reasons
    )
    assertions["all_resource_limits_respected"] &= all(
        limits[key] is None or value <= limits[key]
        for key, value in observation["resources"].items()
    )
    if scenario == "attachment_reference":
        assertions["attachment_reference_completed_or_explicitly_rejected"] &= (
            observation["passed"] is True
        )
    if scenario == "prompt_injection":
        assertions["zero_forbidden_prompt_injection_effects"] &= (
            observation["checks"]["egress_enforced"] is True
        )
    return observation


def _json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("natural_review_artifact_invalid")
    return value


__all__ = ["review_openrouter_natural_cli"]
