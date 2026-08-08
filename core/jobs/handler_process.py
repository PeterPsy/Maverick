"""Killable process boundary and RPC context for server job handlers."""

from __future__ import annotations

import multiprocessing
import math
import os
from dataclasses import replace
from pathlib import Path
import pickle
import shutil
import signal
import tempfile
import time
from typing import Any

from core.jobs.errors import JobCancelledError, JobError, JobHandlerError, JobLeaseError, JobValidationError
from core.jobs.handler_context import JobExecutionContext, JobHandler
from core.jobs.records import JobExecutionResult, JobOutputReference, JobRecord


class BoundedHandlerProcessRunner:
    """Execute one handler behind a bounded forkserver process boundary."""

    def __init__(
        self,
        *,
        max_handler_runtime_seconds: float | None,
        cancellation_grace_seconds: float,
        process_stop_grace_seconds: float,
    ) -> None:
        if max_handler_runtime_seconds is not None and not _positive_finite(max_handler_runtime_seconds):
            raise ValueError("max_handler_runtime_seconds must be positive when provided.")
        if (
            not _non_negative_finite(cancellation_grace_seconds)
            or not _positive_finite(process_stop_grace_seconds)
        ):
            raise ValueError("Server executor process grace periods are invalid.")
        try:
            self.process_context = multiprocessing.get_context("forkserver")
        except ValueError as exc:
            raise RuntimeError("The bounded server executor requires Linux forkserver process support.") from exc
        self.max_handler_runtime_seconds = max_handler_runtime_seconds
        self.cancellation_grace_seconds = cancellation_grace_seconds
        self.process_stop_grace_seconds = process_stop_grace_seconds

    def run(self, context: JobExecutionContext, handler: JobHandler) -> JobExecutionResult:
        scratch_root = Path(tempfile.mkdtemp(prefix="maverick-job-executor-"))
        parent_connection, child_connection = self.process_context.Pipe(duplex=True)
        handler_job = _without_lease_authority(context.job)
        process = self.process_context.Process(
            target=_handler_process_main,
            args=(handler, handler_job, context.executor_id, child_connection, scratch_root),
            name=f"maverick-job-{context.job.job_id}",
        )
        process.daemon = False
        started_at = time.monotonic()
        cancel_requested_at: float | None = None
        runtime_limit = float(context.spec.timeout_seconds or context.spec.budget.max_runtime_seconds)
        if self.max_handler_runtime_seconds is not None:
            runtime_limit = min(runtime_limit, self.max_handler_runtime_seconds)
        try:
            process.start()
            child_connection.close()
            while True:
                message = _receive_message(parent_connection)
                if message is not None:
                    outcome = self._handle_message(context, parent_connection, message)
                    if outcome is not None:
                        return outcome
                current = context.current()
                if current.state == "cancelled":
                    raise JobCancelledError(f"Job `{current.job_id}` was cancelled.")
                if current.state == "cancel_requested":
                    cancel_requested_at = cancel_requested_at or time.monotonic()
                    if time.monotonic() - cancel_requested_at >= self.cancellation_grace_seconds:
                        raise JobCancelledError(f"Job `{current.job_id}` did not stop cooperatively.")
                if time.monotonic() - started_at >= runtime_limit:
                    raise JobHandlerError(
                        "job.handler.timeout",
                        "The registered job handler exceeded its bounded runtime.",
                        retryable=True,
                    )
                if not process.is_alive() and not parent_connection.poll():
                    raise JobHandlerError(
                        "job.handler.crashed",
                        "The registered job handler exited without a result.",
                        retryable=True,
                    )
        finally:
            _stop_process_tree(process, grace_seconds=self.process_stop_grace_seconds)
            parent_connection.close()
            child_connection.close()
            shutil.rmtree(scratch_root, ignore_errors=True)

    @staticmethod
    def _handle_message(context: JobExecutionContext, connection, message: dict[str, Any]) -> JobExecutionResult | None:
        kind = message.get("kind")
        if kind == "request":
            _serve_context_request(context, connection, message)
            return None
        if kind == "result":
            return _execution_result(message.get("value"))
        if kind == "cancelled":
            raise JobCancelledError(f"Job `{context.job.job_id}` was cancelled.")
        if kind == "handler_error":
            raise JobHandlerError(
                str(message.get("error_code") or "job.handler.failed"),
                str(message.get("message") or "The registered job handler failed."),
                retryable=message.get("retryable") is True,
            )
        if kind == "crashed":
            raise RuntimeError(str(message.get("exception_type") or "HandlerCrash"))
        return None


def require_process_safe_handler(handler: JobHandler) -> None:
    try:
        pickle.dumps(handler)
    except (AttributeError, pickle.PickleError, TypeError) as exc:
        raise ValueError("Registered server handlers must be importable process-safe callables.") from exc


def _receive_message(connection) -> dict[str, Any] | None:
    if not connection.poll(0.05):
        return None
    try:
        message = connection.recv()
    except EOFError as exc:
        raise JobHandlerError(
            "job.handler.crashed",
            "The registered job handler exited without a result.",
            retryable=True,
        ) from exc
    return message if isinstance(message, dict) else {}


def _serve_context_request(context: JobExecutionContext, connection, message: dict[str, Any]) -> None:
    request_id = message.get("request_id")
    name = str(message.get("name") or "")
    arguments = message.get("arguments") if isinstance(message.get("arguments"), dict) else {}
    try:
        value = context._command(name, arguments)
        connection.send({"kind": "response", "request_id": request_id, "ok": True, "value": value})
    except JobError as error:
        connection.send(
            {"kind": "response", "request_id": request_id, "ok": False, "error_type": type(error).__name__}
        )
    except Exception:
        connection.send(
            {"kind": "response", "request_id": request_id, "ok": False, "error_type": "JobContextError"}
        )


def _handler_process_main(
    handler: JobHandler,
    job: JobRecord,
    executor_id: str,
    connection,
    scratch_root: Path,
) -> None:
    try:
        _isolate_handler_process(job, scratch_root)
        context = JobExecutionContext(
            job=job,
            executor_id=executor_id,
            lease_token="<redacted>",
            _command=lambda name, arguments: _remote_context_command(connection, name, arguments),
        )
        connection.send({"kind": "result", "value": handler(context)})
    except JobCancelledError:
        _try_send(connection, {"kind": "cancelled"})
    except JobHandlerError as error:
        _try_send(
            connection,
            {
                "kind": "handler_error",
                "error_code": error.error_code,
                "message": error.safe_message,
                "retryable": error.retryable,
            },
        )
    except BaseException as error:
        _try_send(connection, {"kind": "crashed", "exception_type": type(error).__name__})
    finally:
        connection.close()


def _without_lease_authority(job: JobRecord) -> JobRecord:
    if job.lease is None:
        return job
    return replace(job, lease=replace(job.lease, lease_token="<redacted>"))


def _isolate_handler_process(job: JobRecord, scratch_root: Path) -> None:
    os.setsid()
    os.chdir(scratch_root)
    os.environ.clear()
    os.environ.update({"PATH": os.defpath, "LANG": "C.UTF-8"})
    if job.spec.network_policy.mode != "deny_all":
        raise JobHandlerError(
            "job.executor.network_policy_unsupported",
            "The server executor cannot enforce the requested network policy.",
            retryable=False,
        )
    try:
        os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
    except (AttributeError, OSError) as exc:
        raise JobHandlerError(
            "job.executor.isolation_failed",
            "The server executor could not establish deny-all network isolation.",
            retryable=False,
        ) from exc


def _remote_context_command(connection, name: str, arguments: dict[str, Any]):
    request_id = f"request-{time.monotonic_ns()}"
    connection.send({"kind": "request", "request_id": request_id, "name": name, "arguments": arguments})
    response = connection.recv()
    if not isinstance(response, dict) or response.get("request_id") != request_id:
        raise JobHandlerError("job.context.protocol_error", "The handler context protocol failed.", retryable=True)
    if response.get("ok") is True:
        return response.get("value")
    error_type = response.get("error_type")
    if error_type == "JobCancelledError":
        raise JobCancelledError("The job was cancelled.")
    if error_type == "JobLeaseError":
        raise JobLeaseError("The job lease is no longer valid.")
    raise JobHandlerError("job.context.rejected", "A handler context operation was rejected.", retryable=False)


def _execution_result(value: object) -> JobExecutionResult:
    if isinstance(value, JobExecutionResult):
        return value
    if not isinstance(value, dict):
        raise JobValidationError("A job handler must return a result object.")
    outputs = value.get("outputs", [])
    metadata = value.get("metadata", {})
    if not isinstance(outputs, list) or not isinstance(metadata, dict):
        raise JobValidationError("A job handler returned an invalid result object.")
    try:
        return JobExecutionResult(
            outputs=tuple(JobOutputReference(**item) for item in outputs),
            metadata=metadata,
        )
    except (TypeError, ValueError) as exc:
        raise JobValidationError("A job handler returned an invalid output reference.") from exc


def _stop_process_tree(process, *, grace_seconds: float) -> None:
    if process.pid is None:
        return
    if process.is_alive():
        _signal_process_group(process, signal.SIGTERM)
        process.join(timeout=grace_seconds)
    if process.is_alive():
        _signal_process_group(process, signal.SIGKILL)
        process.join(timeout=grace_seconds)
    if process.is_alive():
        raise RuntimeError("The bounded job handler process could not be terminated.")
    process.join(timeout=0)
    process.close()


def _signal_process_group(process, signal_number: int) -> None:
    try:
        process_group_id = os.getpgid(process.pid)
        if process_group_id == process.pid:
            os.killpg(process_group_id, signal_number)
            return
    except (OSError, ProcessLookupError):
        pass
    if signal_number == signal.SIGTERM:
        process.terminate()
    else:
        process.kill()


def _try_send(connection, message: dict[str, Any]) -> None:
    try:
        connection.send(message)
    except (BrokenPipeError, EOFError, OSError):
        pass


def _positive_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _non_negative_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
