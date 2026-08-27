"""Private models for the Google Gemini Interactions protocol codec."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GOOGLE_INTERACTIONS_CODEC_ID = "google-gemini-interactions"
GOOGLE_INTERACTIONS_CODEC_VERSION = "3"
GOOGLE_INTERACTIONS_SCHEMA_VERSION = "3"
GOOGLE_INTERACTIONS_CONTENT_TYPE = "application/vnd.maverick.google-interactions+json"
GOOGLE_INTERACTIONS_ENDPOINT = "https://generativelanguage.googleapis.com/v1/interactions?alt=sse"

GoogleInteractionStateMode = Literal["stateful", "stateless"]


@dataclass(frozen=True)
class GooglePendingFunctionCall:
    call_id: str
    name: str


@dataclass(frozen=True)
class GoogleInteractionState:
    """Exact continuation material retained only in provider-private storage."""

    schema_version: str
    mode: GoogleInteractionStateMode
    previous_interaction_id: str | None
    history: tuple[dict[str, object], ...]
    pending_function_calls: tuple[GooglePendingFunctionCall, ...]
    consumed_function_call_ids: tuple[str, ...]


class GoogleInteractionsProtocolError(RuntimeError):
    """Normalized codec or transport error safe to cross the provider boundary."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def google_interaction_error_reason(code: str) -> str:
    if code in {"unauthenticated", "permission_denied"}:
        return "provider_authentication_failed"
    if code == "quota_exceeded":
        return "provider_quota_exceeded"
    if code == "resource_exhausted":
        return "provider_resource_exhausted"
    if code == "rate_limit_exceeded":
        return "provider_rate_limited"
    if code in {"deadline_exceeded", "gateway_timeout"}:
        return "provider_timeout"
    if code in {"invalid_argument", "failed_precondition"}:
        return "provider_request_rejected"
    return "provider_unavailable"
