"""Trusted output promotion and verification registry for durable jobs."""

from __future__ import annotations

from typing import Callable

from core.jobs.errors import JobValidationError
from core.jobs.lifecycle import validate_execution_result
from core.jobs.models import require_identifier
from core.jobs.records import JobExecutionResult, JobRecord


JobOutputPublisher = Callable[[JobRecord, JobExecutionResult], JobExecutionResult]


class JobOutputPublisherRegistry:
    """Resolve one explicit provider interface and fail closed when absent."""

    def __init__(self) -> None:
        self._publishers: dict[str, JobOutputPublisher] = {}

    def register(self, provider_interface: str, publisher: JobOutputPublisher) -> None:
        interface_id = require_identifier(provider_interface, "output_publisher.provider_interface")
        if interface_id in self._publishers:
            raise JobValidationError(f"Output publisher `{interface_id}` is already registered.")
        if not callable(publisher):
            raise JobValidationError("Output publisher must be callable.")
        self._publishers[interface_id] = publisher

    def publish(self, record: JobRecord, result: JobExecutionResult) -> JobExecutionResult:
        grant = record.spec.output_grant
        if grant is None:
            validate_execution_result(record, result)
            return result
        publisher = self._publishers.get(grant.provider_interface)
        if publisher is None:
            raise JobValidationError(
                f"No trusted output publisher is registered for `{grant.provider_interface}`."
            )
        published = publisher(record, result)
        if not isinstance(published, JobExecutionResult):
            raise JobValidationError("Trusted output publisher returned an invalid result.")
        validate_execution_result(record, published)
        return published
