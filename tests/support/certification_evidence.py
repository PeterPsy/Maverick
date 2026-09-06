"""Fabricated observations for unit tests ONLY; never operational evidence."""

from datetime import UTC, datetime
import json
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from core.providers.certification_behavior import BEHAVIORAL_SCENARIOS, ZERO_TOLERANCE_COUNTERS
from core.providers.certification_target import (
    api_certification_resource_limits, builtin_api_certification_profile,
    builtin_api_certification_target, builtin_api_reasoning_efforts,
)
from core.runtime.execution_binding import canonical_digest


def fixture_live_receipt(provider_id, *, nonce):
    efforts = builtin_api_reasoning_efforts(provider_id)
    common = {
        "target_digest": builtin_api_certification_target(provider_id),
        "run_nonce": nonce, "succeeded": True, "reasoning_efforts": list(efforts),
    }
    if provider_id == "google-ai-studio":
        summary = {
            "reason_code": "ok", "request_count": 3, "saw_streaming": True,
            "saw_tool_call": True, "saw_filesystem_list": True, "saw_usage": True,
            "saw_private_state": True, "reasoning_efforts": list(efforts),
        }
        return {
            **common, **summary, "result_summary_digest": canonical_digest(summary),
            "test_run_id": "google-interactions-live:00000000-0000-0000-0000-000000000000",
        }
    return {
        **common, "request_count": 16, "filesystem_result_count": 12,
        "catalog_snapshot_digest": "a" * 64, "catalog_model_record_digest": "b" * 64,
        "catalog_zdr_record_digest": "c" * 64, "context_length": 1_048_576,
        "max_completion_tokens": 65_536, "supports_tool_choice_none": True,
        "upstream_id": "deepinfra/fp8",
    }


def fixture_step_process(command, **kwargs):
    providers = {"scripts/run_google_interactions_probe.py": "google-ai-studio",
                 "scripts/run_openrouter_agentic_probe.py": "openrouter"}
    provider = providers.get(command[-1])
    stdout = b"passed" if provider is None else json.dumps(fixture_live_receipt(
        provider, nonce=kwargs["env"]["MAVERICK_CERTIFICATION_RUN_NONCE"],
    )).encode()
    return CompletedProcess(command, 0, stdout=stdout, stderr=b"")


def fixture_behavior_report(run, *, provider_id):
    efforts = builtin_api_reasoning_efforts(provider_id)
    limits = api_certification_resource_limits(builtin_api_certification_profile(provider_id))
    started = datetime.now(tz=UTC)
    observations = [
        {
            "scenario_id": scenario, "reasoning_effort": effort, "passed": True,
            "checks": {check: True for check in checks},
            "prompt_digest": "1" * 64, "trace_digest": "2" * 64,
            "semantic_source_digest": "3" * 64, "semantic_projection_digest": "4" * 64,
            "effect_digest": "5" * 64, "resources": {key: 1 for key in limits},
        }
        for effort in efforts for scenario, checks in BEHAVIORAL_SCENARIOS.items()
    ]
    return {
        "schema": "maverick-agentic-natural-conformance.v1", "scope": "api_profile",
        "target_digest": run.target_digest, "source_commit": run.source_commit,
        "tcb_live_digest": run.tcb_live_digest, "reviewer_ref": "6" * 64,
        "started_at": started.isoformat(), "completed_at": datetime.now(tz=UTC).isoformat(),
        "reasoning_efforts": list(efforts), "observations": observations,
        "counters": {key: 0 for key in ZERO_TOLERANCE_COUNTERS},
    }


def with_fixture_behavior(run):
    from core.providers.certification_manifests import get_certification_manifest
    from core.providers.certification_pipeline import attach_behavioral_evidence

    manifest = get_certification_manifest(run.suite_id, run.suite_version)
    with patch("core.providers.certification_pipeline._git_commit", return_value=run.source_commit):
        return attach_behavioral_evidence(
            run, fixture_behavior_report(run, provider_id=manifest.provider_id),
            cwd=Path(__file__).resolve().parents[2],
        )
