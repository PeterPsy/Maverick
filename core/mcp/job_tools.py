"""Core MCP tools for workspace-scoped durable jobs."""

from __future__ import annotations

from typing import Any

from core.jobs.errors import JobAuthorizationError, JobValidationError
from core.jobs.service import JobService
from core.jobs.surfaces import cancel_job, get_job, list_jobs, submit_job
from core.mcp.core_tool_helpers import WORKSPACE_SAFE, core_mcp_tool
from core.mcp.models import McpInvocationContext, McpToolDefinition


def job_tool_specs(*, job_service: JobService | None) -> list[tuple[McpToolDefinition, Any]]:
    if job_service is None:
        return []

    def submit(arguments: dict, context: McpInvocationContext) -> dict:
        return submit_job(
            job_service,
            arguments,
            workspace_id=_workspace_id(context),
            actor_id=_actor_id(context),
        )

    def list_handler(arguments: dict, context: McpInvocationContext) -> dict:
        return list_jobs(job_service, arguments, workspace_id=_workspace_id(context))

    def get(arguments: dict, context: McpInvocationContext) -> dict:
        return get_job(job_service, arguments, workspace_id=_workspace_id(context))

    def cancel(arguments: dict, context: McpInvocationContext) -> dict:
        if _force_requested(arguments) and context.caller_kind != "operator":
            raise JobAuthorizationError("Forced job cancellation is operator-only.")
        return cancel_job(
            job_service,
            arguments,
            workspace_id=_workspace_id(context),
            actor_id=_actor_id(context),
        )

    specs = [
        ("core.jobs.submit", "Submit one app-job.v1 durable job.", _submit_schema(), submit),
        ("core.jobs.list", "List durable jobs in the trusted workspace.", _list_schema(), list_handler),
        ("core.jobs.get", "Read one durable job and optional bounded history.", _get_schema(), get),
        ("core.jobs.cancel", "Request cooperative or operator-forced cancellation.", _cancel_schema(), cancel),
    ]
    return [
        (
            core_mcp_tool(
                tool_name=tool_name,
                description=description,
                owner_id="jobs",
                invocation_policy=WORKSPACE_SAFE,
                input_schema=schema,
            ),
            handler,
        )
        for tool_name, description, schema, handler in specs
    ]


def _workspace_id(context: McpInvocationContext) -> str:
    if not context.workspace_id:
        raise JobValidationError("A trusted workspace context is required.")
    return context.workspace_id


def _actor_id(context: McpInvocationContext) -> str:
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
