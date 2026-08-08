from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import unittest

from core.jobs.errors import (
    JobIdempotencyConflictError,
    JobLeaseError,
    JobQuotaExceededError,
    JobTransitionError,
    JobValidationError,
)
from core.jobs.records import JobExecutionResult, JobOutputReference, WorkspaceJobQuota
from core.jobs.serialization import job_record_to_document
from core.jobs.service import JobService
from tests.unit.jobs.support import START, changed_spec, make_executor, make_service, make_spec, make_store


class JobServiceLifecycleTestCase(unittest.TestCase):
    def test_input_grants_fail_closed_without_a_trusted_provider_validator(self) -> None:
        service = JobService(make_store(), clock=lambda: START)
        with self.assertRaisesRegex(JobValidationError, "No trusted input validator"):
            service.submit(make_spec(), job_id="unverified-input")

    def test_submit_is_idempotent_and_conflicts_on_changed_spec(self) -> None:
        service, clock = make_service()
        spec = make_spec(submitted_by_actor_id="user-one")

        first = service.submit(spec, job_id="job-one", actor_id="user-one")
        replay = service.submit(spec, job_id="ignored-on-replay", actor_id="user-one")

        self.assertEqual(replay.job_id, first.job_id)
        self.assertEqual(len(service.list_events(first.job_id, workspace_id=spec.workspace_id)), 1)
        with self.assertRaises(JobIdempotencyConflictError):
            service.submit(changed_spec(spec))
        with self.assertRaisesRegex(JobValidationError, "trusted actor"):
            service.submit(spec, actor_id="spoofed-user")

        clock.advance(seconds=7_201)
        self.assertEqual(
            service.submit(spec, actor_id="user-one").job_id,
            first.job_id,
        )

    def test_full_transition_heartbeat_progress_log_and_publish(self) -> None:
        service, clock = make_service()
        service.register_output_publisher("file.content.write", _publish_known_output)
        service.advertise_executor(make_executor())
        record = service.submit(make_spec(), job_id="job-one")

        leased = service.lease(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_seconds=20,
        )
        assert leased.lease is not None
        clock.advance(seconds=5)
        heartbeat = service.heartbeat(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            extend_seconds=20,
        )
        self.assertEqual(heartbeat.lease.heartbeat_at, clock.now)  # type: ignore[union-attr]
        service.advance(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            state="preparing",
        )
        service.advance(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            state="running",
        )
        service.report_progress(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            phase="work",
            completed=1,
            total=2,
            unit="items",
            message="private free-form progress",
        )
        service.record_log(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            level="info",
            code="work.completed",
            fields={"token": "secret-value", "safe": "value"},
        )
        service.advance(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            state="validating",
        )
        service.advance(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            state="publishing",
        )
        completed = service.complete(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            result=JobExecutionResult(
                outputs=(
                    JobOutputReference(
                        grant_id="output-grant",
                        resource_id="file-result",
                        sha256="b" * 64,
                        size_bytes=10,
                        mime_type="application/octet-stream",
                    ),
                ),
                metadata={"verified": True, "lease_authority": leased.lease.lease_token},
            ),
        )

        self.assertEqual(completed.state, "succeeded")
        self.assertIsNone(completed.lease)
        self.assertEqual(
            completed.result.metadata,
            {"verified": True, "lease_authority": "<redacted>"},  # type: ignore[union-attr]
        )
        logs = service.list_logs(record.job_id, workspace_id=record.spec.workspace_id)
        self.assertEqual(logs[0].fields, {"token": "<redacted>", "safe": "value"})
        events = service.list_events(record.job_id, workspace_id=record.spec.workspace_id)
        progress_events = [event for event in events if event.payload.get("progress")]
        self.assertTrue(progress_events)
        self.assertNotIn("message", progress_events[-1].payload["progress"])
        audits = service.list_audits(record.job_id, workspace_id=record.spec.workspace_id)
        self.assertEqual(len(audits), len(events))
        self.assertEqual(audits[0].attempt, 0)
        self.assertTrue(all(audit.workspace_id == "workspace-a" for audit in audits))
        self.assertTrue(all(audit.job_id == "job-one" for audit in audits))

    def test_output_completion_fails_closed_without_a_trusted_publisher(self) -> None:
        service, _clock = make_service()
        service.advertise_executor(make_executor())
        record = service.submit(make_spec(), job_id="unpublished-job")
        leased = service.lease(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=20,
        )
        assert leased.lease is not None
        for state in ("preparing", "running", "validating", "publishing"):
            service.advance(
                record.job_id,
                workspace_id="workspace-a",
                executor_id="executor-a",
                lease_token=leased.lease.lease_token,
                state=state,
            )
        result = JobExecutionResult(
            outputs=(
                JobOutputReference(
                    grant_id="output-grant",
                    resource_id="file-result",
                    sha256="b" * 64,
                    size_bytes=10,
                    mime_type="application/octet-stream",
                ),
            ),
            metadata={},
        )

        with self.assertRaisesRegex(JobValidationError, "No trusted output publisher"):
            service.complete(
                record.job_id,
                workspace_id="workspace-a",
                executor_id="executor-a",
                lease_token=leased.lease.lease_token,
                result=result,
            )

        self.assertEqual(service.get(record.job_id, workspace_id="workspace-a").state, "publishing")

    def test_progress_failure_and_log_text_are_redacted_and_logs_are_retained_bounded(self) -> None:
        service, _clock = make_service()
        service.store.max_log_records_per_job = 2
        service.advertise_executor(make_executor())
        record = service.submit(make_spec(with_output=False), job_id="redaction-job")
        leased = service.lease(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=20,
        )
        assert leased.lease is not None
        service.advance(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            state="preparing",
        )
        service.advance(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            state="running",
        )
        progress = service.report_progress(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            phase="work",
            completed=1,
            message="Authorization: Bearer secret-token-value",
        )
        for index in range(3):
            service.record_log(
                record.job_id,
                workspace_id="workspace-a",
                executor_id="executor-a",
                lease_token=leased.lease.lease_token,
                level="info",
                code=f"work.log.{index}",
                fields={
                    "detail": "Authorization: Bearer secret-token-value",
                    "lease_authority": leased.lease.lease_token,
                },
            )

        self.assertNotIn("secret-token-value", progress.progress.message)  # type: ignore[union-attr]
        logs = service.list_logs(record.job_id, workspace_id="workspace-a")
        self.assertEqual(len(logs), 2)
        self.assertNotIn("secret-token-value", str(logs))
        self.assertNotIn(leased.lease.lease_token, str(logs))

    def test_invalid_transition_lease_owner_and_result_fail_closed(self) -> None:
        service, _clock = make_service()
        service.advertise_executor(make_executor())
        record = service.submit(make_spec(), job_id="job-one")
        leased = service.lease(
            record.job_id,
            workspace_id=record.spec.workspace_id,
            executor_id="executor-a",
            lease_seconds=20,
        )
        assert leased.lease is not None
        with self.assertRaises(JobLeaseError):
            service.advance(
                record.job_id,
                workspace_id=record.spec.workspace_id,
                executor_id="executor-a",
                lease_token="wrong-token",
                state="preparing",
            )
        with self.assertRaises(JobTransitionError):
            service.advance(
                record.job_id,
                workspace_id=record.spec.workspace_id,
                executor_id="executor-a",
                lease_token=leased.lease.lease_token,
                state="publishing",
            )
        with self.assertRaises(JobValidationError):
            service.report_progress(
                record.job_id,
                workspace_id=record.spec.workspace_id,
                executor_id="executor-a",
                lease_token=leased.lease.lease_token,
                phase="work",
                completed=True,
            )

    def test_cancel_is_immediate_when_queued_and_cooperative_when_running(self) -> None:
        service, _clock = make_service()
        service.advertise_executor(make_executor())
        queued = service.submit(make_spec(idempotency_key="queued"), job_id="queued-job")
        self.assertEqual(
            service.request_cancel(queued.job_id, workspace_id="workspace-a", reason="user request").state,
            "cancelled",
        )

        running = service.submit(make_spec(idempotency_key="running"), job_id="running-job")
        leased = service.lease(
            running.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=20,
        )
        assert leased.lease is not None
        requested = service.request_cancel(running.job_id, workspace_id="workspace-a", reason="stop")
        self.assertEqual(requested.state, "cancel_requested")
        cancelled = service.acknowledge_cancel(
            running.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
        )
        self.assertEqual(cancelled.state, "cancelled")

    def test_retry_backoff_lease_recovery_and_hard_expiry(self) -> None:
        service, clock = make_service()
        service.advertise_executor(make_executor())
        record = service.submit(make_spec(max_attempts=2), job_id="retry-job")
        leased = service.lease(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=10,
        )
        assert leased.lease is not None
        retried = service.fail(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_token=leased.lease.lease_token,
            error_code="temporary",
            message="safe failure",
            retryable=True,
        )
        self.assertEqual(retried.state, "queued")
        self.assertEqual(retried.available_at, START + timedelta(seconds=5))
        clock.advance(seconds=5)
        leased_again = service.lease(
            record.job_id,
            workspace_id="workspace-a",
            executor_id="executor-a",
            lease_seconds=10,
        )
        clock.advance(seconds=11)
        recovered = service.recover_expired_jobs()
        self.assertEqual(recovered[0].job_id, leased_again.job_id)
        self.assertEqual(recovered[0].state, "expired")

        hard_spec = replace(
            make_spec(idempotency_key="hard-expiry"),
            expires_at=clock.now + timedelta(seconds=2),
            input_grants=(),
            output_grant=None,
        )
        hard = service.submit(hard_spec, job_id="hard-expiry-job")
        clock.advance(seconds=3)
        recovered = service.recover_expired_jobs()
        self.assertEqual(recovered[0].job_id, hard.job_id)
        self.assertEqual(recovered[0].state, "expired")

    def test_recovery_fails_closed_for_a_leased_record_without_lease_authority(self) -> None:
        service, _clock = make_service()
        submitted = service.submit(make_spec(with_output=False), job_id="corrupt-job")
        malformed = replace(submitted, state="running", attempt=1, revision=1, lease=None)
        service.store.collections.jobs.update_one(
            {"workspace_id": "workspace-a", "job_id": "corrupt-job"},
            {
                "$set": {
                    **job_record_to_document(malformed),
                    "workspace_id": "workspace-a",
                    "idempotency_key": malformed.spec.idempotency_key,
                }
            },
        )

        recovered = service.recover_expired_jobs()

        self.assertEqual(recovered[0].job_id, "corrupt-job")
        self.assertEqual(recovered[0].state, "queued")
        self.assertIsNone(recovered[0].lease)

    def test_quota_limits_submission_and_resources(self) -> None:
        service, _clock = make_service()
        service.configure_quota(
            WorkspaceJobQuota("workspace-a", 1, 1, 1, 256, 0, START)
        )
        service.submit(make_spec(idempotency_key="one"), job_id="one")
        with self.assertRaises(JobQuotaExceededError):
            service.submit(make_spec(idempotency_key="two"), job_id="two")
        replay = service.submit(make_spec(idempotency_key="one"), job_id="ignored")
        self.assertEqual(replay.job_id, "one")


def _publish_known_output(_record, result):
    if any(output.resource_id != "file-result" for output in result.outputs):
        raise JobValidationError("Output provider could not reconcile the resource.")
    return result


if __name__ == "__main__":
    unittest.main()
