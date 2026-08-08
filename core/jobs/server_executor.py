"""Server-side orchestration for explicitly registered app-owned handlers."""

from __future__ import annotations

from typing import Any

from core.jobs.errors import JobCancelledError, JobError, JobHandlerError, JobLeaseError, JobValidationError
from core.jobs.handler_process import (
    BoundedHandlerProcessRunner,
    require_process_safe_handler,
)
from core.jobs.handler_context import HandlerKey, JobExecutionContext, JobHandler
from core.jobs.executor_models import ExecutorAdvertisement
from core.jobs.records import JobRecord
from core.jobs.service import JobService


class ServerJobExecutor:
    """Claim jobs and coordinate their handler-driven state machine."""

    def __init__(
        self,
        service: JobService,
        *,
        advertisement: ExecutorAdvertisement,
        handlers: dict[HandlerKey, JobHandler],
        lease_seconds: int = 30,
        max_handler_runtime_seconds: float | None = None,
        cancellation_grace_seconds: float = 2.0,
        process_stop_grace_seconds: float = 1.0,
    ) -> None:
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 1 <= lease_seconds <= 86_400:
            raise ValueError("lease_seconds must be an integer between 1 and 86400.")
        if advertisement.network_modes != ("deny_all",):
            raise ValueError("The server executor supports only enforced deny-all networking.")
        advertised_keys = {
            (capability.job_type, capability.handler_name, version)
            for capability in advertisement.handlers
            for version in capability.handler_versions
        }
        if set(handlers) != advertised_keys:
            raise ValueError("Registered server handlers must exactly match the executor advertisement.")
        for handler in handlers.values():
            require_process_safe_handler(handler)
        self.service = service
        self.advertisement = advertisement
        self.handlers = dict(handlers)
        self.lease_seconds = lease_seconds
        self.process_runner = BoundedHandlerProcessRunner(
            max_handler_runtime_seconds=max_handler_runtime_seconds,
            cancellation_grace_seconds=cancellation_grace_seconds,
            process_stop_grace_seconds=process_stop_grace_seconds,
        )

    def advertise(self) -> ExecutorAdvertisement:
        return self.service.advertise_executor(self.advertisement)

    def run_once(self) -> JobRecord | None:
        leased = self.service.claim_next(
            executor_id=self.advertisement.executor_id,
            lease_seconds=self.lease_seconds,
        )
        if leased is None:
            return None
        assert leased.lease is not None
        context = JobExecutionContext(
            job=leased,
            executor_id=self.advertisement.executor_id,
            lease_token=leased.lease.lease_token,
            _command=self._context_command(leased),
        )
        key = (leased.spec.job_type, leased.spec.handler_name, leased.spec.handler_version)
        handler = self.handlers.get(key)
        if handler is None:
            return self._safe_fail(context, "job.handler.incompatible", "No compatible registered handler exists.", False)
        try:
            self._advance(context, "preparing")
            self._advance(context, "running")
            result = self.process_runner.run(context, handler)
            context.checkpoint()
            self._advance(context, "validating")
            self._advance(context, "publishing")
            return self.service.complete(
                leased.job_id,
                workspace_id=leased.spec.workspace_id,
                executor_id=context.executor_id,
                lease_token=context.lease_token,
                result=result,
            )
        except JobCancelledError:
            current = context.current()
            if current.state == "cancel_requested":
                return self.service.acknowledge_cancel(
                    leased.job_id,
                    workspace_id=leased.spec.workspace_id,
                    executor_id=context.executor_id,
                    lease_token=context.lease_token,
                )
            return current
        except JobLeaseError:
            self.service.recover_expired_jobs()
            return context._command("current_unfenced", {})
        except JobHandlerError as error:
            return self._safe_fail(context, error.error_code, error.safe_message, error.retryable)
        except Exception as error:
            try:
                context.log(
                    level="error",
                    code="job.handler.crashed",
                    fields={"exception_type": type(error).__name__},
                )
            except JobError:
                return context.current()
            return self._safe_fail(
                context,
                "job.handler.crashed",
                "The registered job handler crashed.",
                True,
            )

    def _advance(self, context: JobExecutionContext, state: str) -> JobRecord:
        return self.service.advance(
            context.job.job_id,
            workspace_id=context.job.spec.workspace_id,
            executor_id=context.executor_id,
            lease_token=context.lease_token,
            state=state,  # type: ignore[arg-type]
        )

    def _safe_fail(
        self,
        context: JobExecutionContext,
        error_code: str,
        message: str,
        retryable: bool,
    ) -> JobRecord:
        try:
            return self.service.fail(
                context.job.job_id,
                workspace_id=context.job.spec.workspace_id,
                executor_id=context.executor_id,
                lease_token=context.lease_token,
                error_code=error_code,
                message=message,
                retryable=retryable,
            )
        except JobLeaseError:
            self.service.recover_expired_jobs()
            return context.current()

    def _context_command(self, leased: JobRecord):
        workspace_id = leased.spec.workspace_id
        job_id = leased.job_id
        executor_id = self.advertisement.executor_id
        lease_token = leased.lease.lease_token if leased.lease else ""

        def command(name: str, arguments: dict[str, Any]):
            current = self.service.get(job_id, workspace_id=workspace_id)
            if name == "current_unfenced":
                return current
            if name in {"current", "checkpoint"}:
                if current.state in {"cancel_requested", "cancelled"}:
                    if name == "checkpoint":
                        raise JobCancelledError(f"Job `{job_id}` was cancelled.")
                    return current
                from core.jobs.lifecycle import require_lease

                require_lease(current, executor_id=executor_id, lease_token=lease_token, now=self.service.clock())
                return current
            if name in {"progress", "heartbeat", "log"}:
                command("checkpoint", {})
            if name == "progress":
                return self.service.report_progress(
                    job_id,
                    workspace_id=workspace_id,
                    executor_id=executor_id,
                    lease_token=lease_token,
                    **arguments,
                )
            if name == "heartbeat":
                return self.service.heartbeat(
                    job_id,
                    workspace_id=workspace_id,
                    executor_id=executor_id,
                    lease_token=lease_token,
                    **arguments,
                )
            if name == "log":
                return self.service.record_log(
                    job_id,
                    workspace_id=workspace_id,
                    executor_id=executor_id,
                    lease_token=lease_token,
                    **arguments,
                )
            raise JobValidationError("The handler requested an unknown context operation.")

        return command


__all__ = ["JobExecutionContext", "ServerJobExecutor"]
