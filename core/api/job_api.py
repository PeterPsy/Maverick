"""Authenticated workspace HTTP API for generic durable jobs."""

from __future__ import annotations

from typing import Iterable

from core.api.http import StartResponse, json_response, query_params, read_json_body
from core.api.session_api import resolve_request_session
from core.jobs.errors import (
    ExecutorCompatibilityError,
    JobConcurrencyError,
    JobAuthorizationError,
    JobError,
    JobIdempotencyConflictError,
    JobNotFoundError,
    JobQuotaExceededError,
    JobValidationError,
)
from core.jobs.surfaces import cancel_job, get_job, list_jobs, submit_job


JOBS_API_PREFIX = "/api/jobs"


def handle_job_api(state, environ: dict, start_response: StartResponse) -> Iterable[bytes] | None:
    path = str(environ.get("PATH_INFO") or "")
    if path != JOBS_API_PREFIX and not path.startswith(f"{JOBS_API_PREFIX}/"):
        return None
    context = resolve_request_session(state, environ)
    if context is None:
        return json_response(start_response, {"error": "authentication_required"}, status="401 Unauthorized")
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    try:
        if path == JOBS_API_PREFIX:
            if method == "GET":
                return json_response(
                    start_response,
                    list_jobs(state.job_service, query_params(environ), workspace_id=context.workspace_id),
                )
            if method == "POST":
                return json_response(
                    start_response,
                    submit_job(
                        state.job_service,
                        read_json_body(environ),
                        workspace_id=context.workspace_id,
                        actor_id=context.user.user_id,
                    ),
                    status="201 Created",
                )
            return _method_not_allowed(start_response)
        remainder = path.removeprefix(f"{JOBS_API_PREFIX}/")
        job_id, separator, action = remainder.partition("/")
        if not job_id or (separator and action != "cancel") or "/" in action:
            return json_response(start_response, {"error": "job_route_not_found"}, status="404 Not Found")
        if not separator and method == "GET":
            return json_response(
                start_response,
                get_job(
                    state.job_service,
                    {"job_id": job_id, **query_params(environ)},
                    workspace_id=context.workspace_id,
                ),
            )
        if action == "cancel" and method == "POST":
            body = read_json_body(environ)
            if body.get("force") is True and not _can_force_cancel(state, context):
                raise JobAuthorizationError("Forced cancellation requires workspace or platform admin authority.")
            return json_response(
                start_response,
                cancel_job(
                    state.job_service,
                    {"job_id": job_id, **body},
                    workspace_id=context.workspace_id,
                    actor_id=context.user.user_id,
                ),
            )
        return _method_not_allowed(start_response)
    except JobNotFoundError as error:
        return _job_error(start_response, error, status="404 Not Found")
    except (JobIdempotencyConflictError, JobConcurrencyError) as error:
        return _job_error(start_response, error, status="409 Conflict")
    except JobQuotaExceededError as error:
        return _job_error(start_response, error, status="429 Too Many Requests")
    except JobAuthorizationError as error:
        return _job_error(start_response, error, status="403 Forbidden")
    except (JobValidationError, ExecutorCompatibilityError) as error:
        return _job_error(start_response, error, status="400 Bad Request")
    except JobError as error:
        return _job_error(start_response, error, status="409 Conflict")


def _method_not_allowed(start_response: StartResponse) -> list[bytes]:
    return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")


def _job_error(start_response: StartResponse, error: Exception, *, status: str) -> list[bytes]:
    return json_response(
        start_response,
        {"error": type(error).__name__, "detail": str(error)},
        status=status,
    )


def _can_force_cancel(state, context) -> bool:
    if context.user.platform_role == "admin":
        return True
    try:
        membership = state.workspace_store.get_membership(
            user_id=context.user.user_id,
            workspace_id=context.workspace_id,
        )
    except Exception:
        return False
    return membership.status == "active" and membership.role == "admin"
