from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from threading import Thread
import time
import unittest

from core.jobs.errors import JobHandlerError
from core.jobs.server_executor import ServerJobExecutor
from tests.unit.jobs.support import make_executor, make_service, make_spec


def successful_handler(context):
    context.progress(phase="handler", completed=1, total=1)
    context.log(level="info", code="handler.finished", fields={"ok": True})
    return {"outputs": [], "metadata": {"value": context.spec.parameters["value"]}}


def retryable_handler_failure(_context):
    raise JobHandlerError("temporary.failure", "A safe failure occurred.", retryable=True)


def cooperative_handler(context):
    while True:
        context.checkpoint()
        time.sleep(0.01)


def sleeping_handler(_context):
    time.sleep(10)
    return {"outputs": [], "metadata": {}}


def crashing_handler(_context):
    raise RuntimeError("raw secret must never be persisted")


def descendant_handler(context):
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    context.log(level="info", code="handler.descendant.started", fields={"pid": process.pid})
    time.sleep(30)
    return {"outputs": [], "metadata": {}}


def network_probe_handler(context):
    probe = socket.socket()
    probe.settimeout(0.2)
    try:
        probe.connect(("127.0.0.1", int(context.spec.parameters["port"])))
        connected = True
    except OSError:
        connected = False
    finally:
        probe.close()
    return {"outputs": [], "metadata": {"connected": connected}}


def authority_probe_handler(context):
    context.log(
        level="info",
        code="handler.authority.probe",
        fields={
            "context_lease": context.lease_token,
            "record_lease": context.job.lease.lease_token if context.job.lease else None,
        },
    )
    return {"outputs": [], "metadata": {}}


class ServerJobExecutorTestCase(unittest.TestCase):
    def test_registered_handler_runs_complete_state_machine(self) -> None:
        service, _clock = make_service()
        advertisement = make_executor()
        executor = ServerJobExecutor(
            service,
            advertisement=advertisement,
            handlers={("test.compute", "test-handler", "1"): successful_handler},
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")

        completed = executor.run_once()

        assert completed is not None
        self.assertEqual(completed.state, "succeeded")
        self.assertEqual(completed.result.metadata, {"value": 1})  # type: ignore[union-attr]
        states = [event.state for event in service.list_events("job-one", workspace_id="workspace-a")]
        self.assertEqual(
            states,
            ["queued", "leased", "preparing", "running", "running", "validating", "publishing", "succeeded"],
        )

    def test_handler_failure_uses_declared_retry_policy(self) -> None:
        service, _clock = make_service()
        advertisement = make_executor()

        executor = ServerJobExecutor(
            service,
            advertisement=advertisement,
            handlers={("test.compute", "test-handler", "1"): retryable_handler_failure},
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")

        failed_attempt = executor.run_once()

        assert failed_attempt is not None
        self.assertEqual(failed_attempt.state, "queued")
        self.assertEqual(failed_attempt.failure.error_code, "temporary.failure")  # type: ignore[union-attr]

    def test_handler_observes_cooperative_cancellation(self) -> None:
        service, _clock = make_service()
        advertisement = make_executor()
        executor = ServerJobExecutor(
            service,
            advertisement=advertisement,
            handlers={("test.compute", "test-handler", "1"): cooperative_handler},
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")
        results = []
        thread = Thread(target=lambda: results.append(executor.run_once()))
        thread.start()
        self.assertTrue(_wait_for_state(service, "job-one", "running"))
        service.request_cancel("job-one", workspace_id="workspace-a", reason="stop")
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        cancelled = results[0]
        assert cancelled is not None
        self.assertEqual(cancelled.state, "cancelled")

    def test_forced_cancellation_terminates_a_non_cooperative_handler_process(self) -> None:
        service, _clock = make_service()
        executor = ServerJobExecutor(
            service,
            advertisement=make_executor(),
            handlers={("test.compute", "test-handler", "1"): sleeping_handler},
            cancellation_grace_seconds=0.05,
            process_stop_grace_seconds=0.1,
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")
        results = []
        thread = Thread(target=lambda: results.append(executor.run_once()))
        thread.start()
        self.assertTrue(_wait_for_state(service, "job-one", "running"))
        service.request_cancel("job-one", workspace_id="workspace-a", reason="operator", force=True)
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].state, "cancelled")

    def test_handler_runtime_is_bounded_and_timeout_is_redaction_safe(self) -> None:
        service, _clock = make_service()

        executor = ServerJobExecutor(
            service,
            advertisement=make_executor(),
            handlers={("test.compute", "test-handler", "1"): sleeping_handler},
            max_handler_runtime_seconds=0.05,
            process_stop_grace_seconds=0.1,
        )
        executor.advertise()
        service.submit(make_spec(with_output=False, max_attempts=1), job_id="job-one")

        timed_out = executor.run_once()

        assert timed_out is not None
        self.assertEqual(timed_out.state, "failed")
        self.assertEqual(timed_out.failure.error_code, "job.handler.timeout")  # type: ignore[union-attr]

    def test_expired_lease_stops_handler_and_runs_recovery(self) -> None:
        service, clock = make_service()
        executor = ServerJobExecutor(
            service,
            advertisement=make_executor(),
            handlers={("test.compute", "test-handler", "1"): sleeping_handler},
            process_stop_grace_seconds=0.1,
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")
        results = []
        thread = Thread(target=lambda: results.append(executor.run_once()))
        thread.start()
        self.assertTrue(_wait_for_state(service, "job-one", "running"))

        clock.advance(seconds=31)
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].state, "queued")
        self.assertIsNone(results[0].lease)

    def test_forced_cancellation_terminates_the_handler_process_group(self) -> None:
        service, _clock = make_service()
        executor = ServerJobExecutor(
            service,
            advertisement=make_executor(),
            handlers={("test.compute", "test-handler", "1"): descendant_handler},
            process_stop_grace_seconds=0.1,
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")
        results = []
        thread = Thread(target=lambda: results.append(executor.run_once()))
        thread.start()
        descendant_pid = _wait_for_descendant_pid(service, "job-one")
        self.assertIsNotNone(descendant_pid)
        assert descendant_pid is not None
        try:
            service.request_cancel("job-one", workspace_id="workspace-a", reason="operator", force=True)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results[0].state, "cancelled")
            self.assertTrue(_wait_for_process_exit(descendant_pid))
        finally:
            if _process_exists(descendant_pid):
                os.kill(descendant_pid, signal.SIGKILL)

    def test_server_handler_process_enforces_deny_all_networking(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        try:
            service, _clock = make_service()
            executor = ServerJobExecutor(
                service,
                advertisement=make_executor(),
                handlers={("test.compute", "test-handler", "1"): network_probe_handler},
            )
            executor.advertise()
            spec = make_spec(with_output=False)
            from dataclasses import replace

            service.submit(replace(spec, parameters={"port": listener.getsockname()[1]}), job_id="job-one")

            completed = executor.run_once()

            assert completed is not None
            self.assertEqual(completed.state, "succeeded")
            self.assertEqual(completed.result.metadata, {"connected": False})  # type: ignore[union-attr]
        finally:
            listener.close()

    def test_unexpected_exception_is_redaction_safe_and_retryable(self) -> None:
        service, _clock = make_service()
        advertisement = make_executor()

        executor = ServerJobExecutor(
            service,
            advertisement=advertisement,
            handlers={("test.compute", "test-handler", "1"): crashing_handler},
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")

        failed_attempt = executor.run_once()

        assert failed_attempt is not None
        self.assertEqual(failed_attempt.failure.message, "The registered job handler crashed.")  # type: ignore[union-attr]
        logs = service.list_logs("job-one", workspace_id="workspace-a")
        self.assertEqual(logs[0].fields, {"exception_type": "RuntimeError"})

    def test_handler_process_never_receives_lease_authority(self) -> None:
        service, _clock = make_service()
        executor = ServerJobExecutor(
            service,
            advertisement=make_executor(),
            handlers={("test.compute", "test-handler", "1"): authority_probe_handler},
        )
        executor.advertise()
        service.submit(make_spec(with_output=False), job_id="job-one")

        completed = executor.run_once()

        assert completed is not None
        self.assertEqual(completed.state, "succeeded")
        logs = service.list_logs("job-one", workspace_id="workspace-a")
        self.assertEqual(
            logs[0].fields,
            {"context_lease": "<redacted>", "record_lease": "<redacted>"},
        )

    def test_registered_handlers_must_match_advertisement_exactly(self) -> None:
        service, _clock = make_service()
        with self.assertRaisesRegex(ValueError, "exactly match"):
            ServerJobExecutor(service, advertisement=make_executor(), handlers={})

    def test_registered_handlers_must_be_process_safe(self) -> None:
        service, _clock = make_service()
        with self.assertRaisesRegex(ValueError, "process-safe"):
            ServerJobExecutor(
                service,
                advertisement=make_executor(),
                handlers={("test.compute", "test-handler", "1"): lambda _context: {}},
            )


def _wait_for_state(service, job_id: str, state: str, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service.get(job_id, workspace_id="workspace-a").state == state:
            return True
        time.sleep(0.01)
    return False


def _wait_for_descendant_pid(service, job_id: str, *, timeout: float = 2.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        logs = service.list_logs(job_id, workspace_id="workspace-a")
        if logs:
            return int(logs[-1].fields["pid"])
        time.sleep(0.01)
    return None


def _wait_for_process_exit(process_id: int, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_exists(process_id):
            return True
        time.sleep(0.01)
    return False


def _process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


if __name__ == "__main__":
    unittest.main()
