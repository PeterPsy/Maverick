from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import math
import json
from pathlib import Path
import unittest

from core.jobs.errors import ExecutorCompatibilityError, JobConcurrencyError, JobValidationError
from core.jobs.models import JobResourceRequirements
from core.jobs.protocol import parse_job_spec
from core.jobs.serialization import job_spec_to_payload
from tests.unit.jobs.support import START, make_executor, make_service, make_spec


class SchedulerExecutorTestCase(unittest.TestCase):
    def test_claim_next_is_workspace_fair_and_priority_ordered(self) -> None:
        service, _clock = make_service()
        service.advertise_executor(make_executor(max_concurrent_jobs=3))
        service.submit(
            make_spec(workspace_id="workspace-a", idempotency_key="a-low", priority=10),
            job_id="a-low",
        )
        service.submit(
            make_spec(workspace_id="workspace-a", idempotency_key="a-high", priority=90),
            job_id="a-high",
        )
        service.submit(
            make_spec(workspace_id="workspace-b", idempotency_key="b", priority=20),
            job_id="b",
        )

        first = service.claim_next(executor_id="executor-a", lease_seconds=30)
        second = service.claim_next(executor_id="executor-a", lease_seconds=30)

        assert first is not None and second is not None
        self.assertEqual(first.job_id, "a-high")
        self.assertEqual(second.job_id, "b")

    def test_executor_selection_uses_handler_runtime_capacity_and_load(self) -> None:
        service, _clock = make_service()
        service.advertise_executor(make_executor(executor_id="executor-a"))
        service.advertise_executor(make_executor(executor_id="executor-b"))
        first = service.submit(make_spec(idempotency_key="one"), job_id="one")
        service.lease(
            first.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=30,
        )

        self.assertEqual(service.select_executor(make_spec(idempotency_key="two")).executor_id, "executor-b")

        oversized = replace(
            make_spec(idempotency_key="oversized"),
            resources=JobResourceRequirements(
                cpu_cores=100,
                ram_bytes=128,
                disk_bytes=64,
                runtime="python",
                runtime_version="3.12",
            ),
        )
        with self.assertRaises(ExecutorCompatibilityError):
            service.select_executor(oversized)

    def test_expired_or_draining_executor_is_not_leaseable(self) -> None:
        service, clock = make_service()
        service.advertise_executor(make_executor(status="draining"))
        job = service.submit(make_spec(), job_id="job-one")
        with self.assertRaises(ExecutorCompatibilityError):
            service.lease(
                job.job_id,
                workspace_id="workspace-a",
                executor_id="executor-a",
                lease_seconds=30,
            )
        clock.advance(seconds=3601)
        with self.assertRaises(ExecutorCompatibilityError):
            service.advertise_executor(make_executor(executor_id="expired"))

    def test_stale_compare_and_set_is_rejected(self) -> None:
        service, _clock = make_service()
        record = service.submit(make_spec(), job_id="job-one")
        stale = replace(record, revision=1, last_mutation_id="stale-mutation")
        with self.assertRaises(JobConcurrencyError):
            service.store.compare_and_set(stale, expected_revision=99)

    def test_protocol_round_trip_and_numeric_validation(self) -> None:
        spec = make_spec()
        parsed = parse_job_spec(job_spec_to_payload(spec))
        self.assertEqual(parsed, spec)
        with self.assertRaises(JobValidationError):
            replace(spec, resources=replace(spec.resources, cpu_cores=math.inf))
        with self.assertRaises(JobValidationError):
            parse_job_spec({"protocol_version": "app-job.v1"})
        with self.assertRaises(JobValidationError):
            parse_job_spec({**job_spec_to_payload(spec), "priority": True})
        with self.assertRaises(JobValidationError):
            parse_job_spec({**job_spec_to_payload(spec), "undeclared": "field"})
        payload_with_defaults = job_spec_to_payload(spec)
        payload_with_defaults.pop("retry")
        payload_with_defaults.pop("network_policy")
        self.assertEqual(parse_job_spec(payload_with_defaults).retry.max_attempts, 1)

    def test_heartbeat_is_capped_by_job_deadline(self) -> None:
        service, clock = make_service()
        service.advertise_executor(make_executor())
        spec = replace(
            make_spec(),
            expires_at=START + timedelta(seconds=10),
            input_grants=(),
            output_grant=None,
        )
        job = service.submit(spec, job_id="deadline")
        leased = service.lease(
            job.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=100,
        )
        assert leased.lease is not None
        self.assertEqual(leased.lease.expires_at, START + timedelta(seconds=10))
        clock.advance(seconds=5)
        heartbeat = service.heartbeat(
            job.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            extend_seconds=100,
        )
        self.assertEqual(heartbeat.lease.expires_at, START + timedelta(seconds=10))  # type: ignore[union-attr]

    def test_claim_recovers_expired_queued_work_before_scheduling(self) -> None:
        service, clock = make_service()
        service.advertise_executor(make_executor())
        expiring = replace(
            make_spec(idempotency_key="expiring", with_output=False),
            input_grants=(),
            expires_at=START + timedelta(seconds=2),
        )
        service.submit(expiring, job_id="expiring")
        service.submit(make_spec(idempotency_key="ready", with_output=False), job_id="ready")
        clock.advance(seconds=3)

        claimed = service.claim_next(executor_id="executor-a", lease_seconds=30)

        assert claimed is not None
        self.assertEqual(claimed.job_id, "ready")
        self.assertEqual(service.get("expiring", workspace_id="workspace-a").state, "expired")

    def test_committed_protocol_schema_is_versioned_and_app_agnostic(self) -> None:
        schema_path = Path("core/jobs/schemas/app-job.v1.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["protocol_version"]["const"], "app-job.v1")
        self.assertIn("idempotency_key", schema["required"])
        self.assertIn("submitted_by_actor_id", schema["required"])
        encoded = json.dumps(schema).lower()
        self.assertNotIn("video", encoded)
        self.assertNotIn("remotion", encoded)
        self.assertNotIn("ffmpeg", encoded)


if __name__ == "__main__":
    unittest.main()
