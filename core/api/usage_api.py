"""Administrative token usage time-series API."""

from __future__ import annotations

from typing import cast

from core.api.http import StartResponse, json_response, query_params
from core.api.platform_state import PlatformState
from core.api.session_api import RequestSession, require_session
from core.usage.models import UsageResolution
from core.usage.timeseries import usage_timeseries_payload


def handle_usage_api(
    state: PlatformState,
    environ: dict,
    start_response: StartResponse,
) -> list[bytes] | None:
    """Serve workspace-local hourly and daily token usage to platform admins."""
    path = str(environ.get("PATH_INFO") or "/")
    if path != "/api/usage/timeseries":
        return None
    context_or_response = require_session(state, environ, start_response)
    if not isinstance(context_or_response, RequestSession):
        return context_or_response
    context = context_or_response
    if str(environ.get("REQUEST_METHOD") or "GET").upper() != "GET":
        return json_response(start_response, {"error": "method_not_allowed"}, status="405 Method Not Allowed")
    if getattr(context.user, "platform_role", None) != "admin":
        return json_response(start_response, {"error": "usage_timeseries_forbidden"}, status="403 Forbidden")
    query = query_params(environ)
    resolution = str(query.get("resolution") or "day").strip().lower()
    if resolution not in {"hour", "day"}:
        return json_response(start_response, {"error": "usage_resolution_invalid"}, status="400 Bad Request")
    default_periods = 24 if resolution == "hour" else 30
    try:
        periods = int(query.get("periods") or default_periods)
    except ValueError:
        return json_response(start_response, {"error": "usage_periods_invalid"}, status="400 Bad Request")
    return json_response(
        start_response,
        usage_timeseries_payload(
            state.usage_store,
            workspace_id=context.workspace_id,
            resolution=cast(UsageResolution, resolution),
            periods=periods,
            provider_id=str(query.get("provider_id") or "").strip() or None,
            model_id=str(query.get("model_id") or "").strip() or None,
        ),
    )
