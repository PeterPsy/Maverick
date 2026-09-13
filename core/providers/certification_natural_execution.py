"""Scenario execution and evidence projection for OpenRouter natural certification."""

from __future__ import annotations

from datetime import UTC, datetime
import json

from core.providers.certification_behavior import ZERO_TOLERANCE_COUNTERS
from core.providers.certification_natural_artifacts import (
    OpenRouterNaturalOperatorConfig,
    artifact_sha256,
    jsonable,
    write_new_json,
)
from core.providers.certification_natural_evidence import (
    natural_observation,
    natural_private_trace,
    natural_scenario_resources,
    workspace_snapshot,
)
from core.providers.certification_natural_lab import (
    certification_natural_lab_permit_payload,
)
from core.providers.certification_natural_runtime import (
    create_session,
    execute_one,
    reload_natural_lab,
)
from core.providers.certification_natural_scenarios import (
    OPENROUTER_NATURAL_LIMITS,
    OPENROUTER_NATURAL_PROMPTS,
    OPENROUTER_NATURAL_SECOND_PROMPTS,
    openrouter_natural_scenario_checks,
)

def run_openrouter_natural_scenario(
    config: OpenRouterNaturalOperatorConfig,
    **values,
) -> int:
    scenario = values["scenario"]
    effort = values["effort"]
    state = values["state"]
    authority = values["authority"]
    adapter = values["adapter"]
    signed = values["signed"]
    ledger = values["ledger"]
    actor_id = values["actor_id"]
    workspace_root = (
        config.repository_root
        / "workspaces"
        / values["workspace_record"].workspace_id
    )
    before = workspace_snapshot(workspace_root)
    session = create_session(
        config,
        state,
        values["definition"],
        values["workspace_binding"],
        values["credential_binding"],
        actor_id,
        effort,
        signed.permit,
        values["adapter_version"],
        scenario,
    )
    outputs: list[str] = []
    public_events: list[object] = []
    authority_digests: list[str] = []
    turn_ids: list[str] = []
    failure_reasons: list[str | None] = []
    elapsed = 0
    reloaded = False
    attachment = None
    if scenario == "attachment_reference":
        attachment = {
            "id": "attachment-natural",
            "name": "note.txt",
            "relativePath": "storage/uploaded/attachment-natural/note.txt",
            "type": "text/plain",
            "size": 19,
        }
    turn_id = f"turn-{session.session_id}-1"
    result, events, took, effective = execute_one(
        state,
        adapter,
        authority,
        session,
        actor_id,
        turn_id,
        OPENROUTER_NATURAL_PROMPTS[scenario],
        skill=values["skill"] if scenario == "skill" else None,
        attachment=attachment,
    )
    _record_turn_result(
        result,
        events,
        took,
        effective,
        turn_id,
        outputs,
        public_events,
        authority_digests,
        turn_ids,
        failure_reasons,
    )
    elapsed += took
    if result.exit_code != 0 and not (
        scenario == "attachment_reference"
        and result.failure_reason_code == "egress_data_class_denied"
    ):
        raise RuntimeError(
            f"natural_scenario_execution_failed:{scenario}:"
            f"{result.failure_reason_code}"
        )
    if scenario in OPENROUTER_NATURAL_SECOND_PROMPTS:
        if scenario == "restart":
            state, authority, adapter, session = reload_natural_lab(
                config,
                signed,
                ledger,
                session.session_id,
            )
            reloaded = True
        turn_id = f"turn-{session.session_id}-2"
        result, events, took, effective = execute_one(
            state,
            adapter,
            authority,
            session,
            actor_id,
            turn_id,
            OPENROUTER_NATURAL_SECOND_PROMPTS[scenario],
        )
        _record_turn_result(
            result,
            events,
            took,
            effective,
            turn_id,
            outputs,
            public_events,
            authority_digests,
            turn_ids,
            failure_reasons,
        )
        elapsed += took
        if result.exit_code != 0:
            raise RuntimeError(
                f"natural_scenario_followup_failed:{scenario}:"
                f"{result.failure_reason_code}"
            )
    invocations = [
        item
        for item in state.runtime_store.list_tool_invocations(
            session_id=session.session_id
        )
        if item.turn_id in turn_ids
    ]
    journals = [
        item
        for item in state.runtime_store.list_provider_step_journals(
            session_id=session.session_id
        )
        if item.turn_id in turn_ids
    ]
    after = workspace_snapshot(workspace_root)
    checks = openrouter_natural_scenario_checks(
        scenario,
        outputs=outputs,
        invocations=invocations,
        journals=journals,
        workspace_root=workspace_root,
        before=before,
        after=after,
        authority_digests=authority_digests,
        reloaded=reloaded,
        failure_reasons=failure_reasons,
    )
    resources = natural_scenario_resources(journals, invocations, elapsed)
    trace = natural_private_trace(
        scenario=scenario,
        effort=effort,
        source_commit=config.source_commit,
        started_at=values["started_at"],
        permit=signed.permit,
        session=session,
        authority_digests=authority_digests,
        outputs=outputs,
        failure_reasons=failure_reasons,
        public_events=public_events,
        invocations=invocations,
        journals=journals,
        before=before,
        after=after,
        checks=checks,
        resources=resources,
    )
    trace_digest = write_new_json(
        values["run_root"] / f"trace-{scenario}.json",
        trace,
    )
    observation = natural_observation(trace, trace_digest, journals, invocations)
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "scenario": scenario,
                "passed": passed,
                "checks": checks,
                "resources": resources,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if not passed:
        raise RuntimeError(f"natural_scenario_checks_failed:{scenario}")
    if any(
        resources[key] > OPENROUTER_NATURAL_LIMITS[key]
        for key in resources
    ):
        raise RuntimeError(f"natural_scenario_resource_limit:{scenario}")
    report = {
        "schema": "maverick-agentic-natural-conformance.v1",
        "scope": "api_profile",
        "target_digest": signed.permit.target_digest,
        "source_commit": config.source_commit,
        "tcb_live_digest": signed.permit.tcb_live_digest,
        "started_at": values["started_at"].isoformat(),
        "completed_at": datetime.now(tz=UTC).isoformat(),
        "reviewer_ref": config.reviewer_ref,
        "observations": [observation],
        "counters": {key: 0 for key in ZERO_TOLERANCE_COUNTERS},
        "reasoning_efforts": [effort],
    }
    report_path = config.job_root / f"behavioral-{values['suffix']}.json"
    report_digest = write_new_json(report_path, report)
    summary = {
        "schema": "maverick-hosted-natural-run.v1",
        "provider_id": "openrouter",
        "reasoning_effort": effort,
        "source_commit": config.source_commit,
        "permit_digest": artifact_sha256(
            certification_natural_lab_permit_payload(signed.permit)
        ),
        "behavioral_report": str(report_path),
        "behavioral_report_digest": report_digest,
        "scenario_count": 1,
        "all_passed": True,
        "ledger_policy_digest": ledger.policy_digest,
        "ledger_status": ledger.status(),
        "completed_at": datetime.now(tz=UTC),
    }
    write_new_json(
        config.job_root / f"natural-summary-{values['suffix']}.json",
        summary,
    )
    print(json.dumps(jsonable(summary), sort_keys=True), flush=True)
    return 0


def _record_turn_result(
    result,
    events,
    took,
    effective,
    turn_id,
    outputs,
    public_events,
    authority_digests,
    turn_ids,
    failure_reasons,
) -> None:
    outputs.append(result.output_text)
    public_events.extend(events)
    authority_digests.append(effective.authority_digest)
    turn_ids.append(turn_id)
    failure_reasons.append(result.failure_reason_code)

__all__ = ["run_openrouter_natural_scenario"]
