"""Core CLI commands for workspace-scoped durable jobs."""

from __future__ import annotations

from typing import Any

from core.cli.core_command_helpers import WORKSPACE_SAFE, core_cli_command
from core.cli.models import CliCommandDefinition, CliInvocationContext
from core.jobs.errors import JobAuthorizationError, JobValidationError
from core.jobs.service import JobService
from core.jobs.surfaces import cancel_job, get_job, list_jobs, submit_job


def job_command_specs(*, job_service: JobService | None) -> list[tuple[CliCommandDefinition, Any]]:
    if job_service is None:
        return []

    def submit(arguments: dict, context: CliInvocationContext) -> dict:
        return submit_job(
            job_service,
            arguments,
            workspace_id=_workspace_id(context),
            actor_id=_actor_id(context),
        )

    def list_handler(arguments: dict, context: CliInvocationContext) -> dict:
        return list_jobs(job_service, arguments, workspace_id=_workspace_id(context))

    def get(arguments: dict, context: CliInvocationContext) -> dict:
        return get_job(job_service, arguments, workspace_id=_workspace_id(context))

    def cancel(arguments: dict, context: CliInvocationContext) -> dict:
        if _force_requested(arguments) and context.caller_kind != "operator":
            raise JobAuthorizationError("Forced job cancellation is operator-only.")
        return cancel_job(
            job_service,
            arguments,
            workspace_id=_workspace_id(context),
            actor_id=_actor_id(context),
        )

    specs = [
        ("core.jobs.submit", ["jobs", "submit"], "Submit one app-job.v1 durable job.", _submit_schema(), submit),
        ("core.jobs.list", ["jobs", "list"], "List durable jobs in the trusted workspace.", _list_schema(), list_handler),
        ("core.jobs.get", ["jobs", "get"], "Read one durable job and optional bounded history.", _get_schema(), get),
        ("core.jobs.cancel", ["jobs", "cancel"], "Request cooperative or operator-forced cancellation.", _cancel_schema(), cancel),
    ]
    return [
        (
            core_cli_command(
                command_id=command_id,
                path_segments=path,
                description=description,
                owner_id="jobs",
                invocation_policy=WORKSPACE_SAFE,
                argument_schema=schema,
            ),
            handler,
        )
        for command_id, path, description, schema, handler in specs
    ]


def _workspace_id(context: CliInvocationContext) -> str:
    if not context.workspace_id:
        raise JobValidationError("A trusted workspace context is required.")
    return context.workspace_id


def _actor_id(context: CliInvocationContext) -> str:
    return context.user_id or context.agent_id or context.caller_kind


def _force_requested(arguments: dict) -> bool:
    value = arguments.get("force")
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _submit_schema() -> dict:
    return {
        "type": "object",
        "properties": {"spec": {"type": "object"}, "job_id": {"type": "string"}},
        "required": ["spec"],
        "additionalProperties": False,
    }


def _list_schema() -> dict:
    return {
        "type": "object",
        "properties": {"state": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
        "additionalProperties": False,
    }


def _get_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "include_history": {"type": "boolean"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "required": ["job_id"],
        "additionalProperties": False,
    }


def _cancel_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
            "reason": {"type": "string"},
            "force": {"type": "boolean"},
        },
        "required": ["job_id", "reason"],
        "additionalProperties": False,
    }
