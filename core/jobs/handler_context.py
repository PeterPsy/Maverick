"""Capability-bounded protocol exposed to app-owned job handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.jobs.records import JobExecutionResult, JobRecord


HandlerKey = tuple[str, str, str]
ContextCommand = Callable[[str, dict[str, Any]], Any]
JobHandler = Callable[["JobExecutionContext"], JobExecutionResult | dict[str, Any]]


@dataclass(frozen=True)
class JobExecutionContext:
    """Capability-bounded context delivered to one registered handler."""

    job: JobRecord
    executor_id: str
    lease_token: str
    _command: ContextCommand

    @property
    def spec(self):
        return self.job.spec

    def current(self) -> JobRecord:
        return self._command("current", {})

    def checkpoint(self) -> JobRecord:
        return self._command("checkpoint", {})

    def progress(
        self,
        *,
        phase: str,
        completed: int,
        total: int | None = None,
        unit: str | None = None,
        message: str | None = None,
    ) -> JobRecord:
        return self._command(
            "progress",
            {"phase": phase, "completed": completed, "total": total, "unit": unit, "message": message},
        )

    def heartbeat(self, *, extend_seconds: int) -> JobRecord:
        return self._command("heartbeat", {"extend_seconds": extend_seconds})

    def log(self, *, level: str, code: str, fields: dict | None = None):
        return self._command("log", {"level": level, "code": code, "fields": fields})
