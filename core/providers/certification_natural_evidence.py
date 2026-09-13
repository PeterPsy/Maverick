"""Trace and observation projection for natural certification."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from core.providers.certification_natural_artifacts import artifact_sha256, jsonable
from core.providers.certification_natural_scenarios import (
    OPENROUTER_NATURAL_PROMPTS,
    OPENROUTER_NATURAL_SECOND_PROMPTS,
)
from core.runtime.execution_binding import canonical_digest


def workspace_snapshot(root: Path) -> str:
    records = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(
            part in {".git", "runtime", "tmp"} for part in relative.parts
        ):
            continue
        records.append(
            (
                relative.as_posix(),
                path.stat().st_size,
                artifact_sha256(path.read_bytes()),
            )
        )
    return canonical_digest(records)

def natural_scenario_resources(journals, invocations, elapsed) -> dict[str, int]:
    return {
        "input_tokens": sum(item.usage_input_tokens for item in journals),
        "output_tokens": sum(item.usage_output_tokens for item in journals),
        "tool_calls": len(invocations),
        "provider_steps": len(journals),
        "wall_time_ms": elapsed,
        "cost_microusd": sum(
            item.usage_cost_microusd or 0 for item in journals
        ),
    }


def natural_private_trace(**values) -> dict[str, object]:
    scenario = values["scenario"]
    prompts = [OPENROUTER_NATURAL_PROMPTS[scenario]]
    if scenario in OPENROUTER_NATURAL_SECOND_PROMPTS:
        prompts.append(OPENROUTER_NATURAL_SECOND_PROMPTS[scenario])
    return {
        "schema": "maverick-natural-private-trace.v1",
        "provider_id": "openrouter",
        "reasoning_effort": values["effort"],
        "scenario_id": scenario,
        "started_at": values["started_at"],
        "completed_at": datetime.now(tz=UTC),
        "source_commit": values["source_commit"],
        "target_digest": values["permit"].target_digest,
        "adapter_artifact_digest": values["permit"].adapter_artifact_digest,
        "tcb_live_digest": values["permit"].tcb_live_digest,
        "session_id": values["session"].session_id,
        "execution_binding_digest": values["session"].execution_binding.binding_digest,
        "authority_digests": values["authority_digests"],
        "prompts": prompts,
        "outputs": values["outputs"],
        "failure_reasons": values["failure_reasons"],
        "public_events": [jsonable(item) for item in values["public_events"]],
        "invocations": [_invocation_trace(item) for item in values["invocations"]],
        "journals": [_journal_trace(item) for item in values["journals"]],
        "workspace_before_digest": values["before"],
        "workspace_after_digest": values["after"],
        "checks": values["checks"],
        "resources": values["resources"],
    }


def _invocation_trace(item) -> dict[str, object]:
    return {
        "invocation_id": item.invocation_id,
        "turn_id": item.turn_id,
        "tool_handle": item.resolved_tool_handle,
        "effect_class": item.effect_class,
        "state": item.state,
        "arguments_digest": item.arguments_digest,
        "result_summary": item.result_summary,
        "result_data_class": item.result_data_class,
        "result_artifact_sha256": item.result_artifact_sha256,
    }


def _journal_trace(item) -> dict[str, object]:
    fields = (
        "journal_id",
        "turn_id",
        "step_index",
        "request_phase",
        "commit_status",
        "pairing_status",
        "semantic_source_snapshot_digest",
        "provider_egress_projection_digest",
        "context_compaction_evidence_digest",
        "context_compaction_applied",
        "usage_input_tokens",
        "usage_output_tokens",
        "usage_cost_microusd",
        "stream_failure_reason_code",
    )
    return {field: getattr(item, field) for field in fields}


def natural_observation(trace, trace_digest, journals, invocations) -> dict[str, object]:
    return {
        "scenario_id": trace["scenario_id"],
        "passed": all(trace["checks"].values()),
        "checks": trace["checks"],
        "prompt_digest": artifact_sha256(
            json.dumps(
                trace["prompts"],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ),
        "trace_digest": trace_digest,
        "semantic_source_digest": canonical_digest(
            [item.semantic_source_snapshot_digest for item in journals]
        ),
        "semantic_projection_digest": canonical_digest(
            [item.provider_egress_projection_digest for item in journals]
        ),
        "effect_digest": canonical_digest(
            {
                "before": trace["workspace_before_digest"],
                "after": trace["workspace_after_digest"],
                "invocations": [
                    (item.invocation_id, item.state, item.result_artifact_sha256)
                    for item in invocations
                ],
            }
        ),
        "reasoning_effort": trace["reasoning_effort"],
        "resources": trace["resources"],
    }


__all__ = [
    "natural_observation",
    "natural_private_trace",
    "natural_scenario_resources",
    "workspace_snapshot",
]
