"""Fixed Chrome observation inputs and shared-platform navigation scope."""

from __future__ import annotations

from typing import Any

from errors import BrowserValidationError
from reading_validation import validate_reading_action
from platform_scope import platform_url, platform_for_url
from interaction_validation import INTERACTION_ACTIONS, INTERACTION_FIELDS, validate_interaction
from website_scope import website_url


COMPANION_COMMANDS = frozenset({
    "navigate", "snapshot", "content.read", "scroll", "screenshot", "video.frame",
    "video.analyze", "content.collect", "tabs", "wait_for",
}) | INTERACTION_ACTIONS
COMMAND_FIELDS = {
    "navigate": {"url", "mode"},
    "snapshot": {"max_chars", "max_items"},
    "content.read": {"max_chars", "max_items"},
    "scroll": {"direction", "pixels", "steps", "settle_ms", "target"},
    "screenshot": {"full_page"},
    "video.frame": {"video_index", "time_seconds"},
    "video.analyze": {"video_index", "frame_count", "max_seconds", "include_audio", "save_evidence"},
    "content.collect": {"urls", "max_items", "max_batches"},
    "tabs": set(),
    "wait_for": {"state", "timeout_ms"},
    **INTERACTION_FIELDS,
}
for _action in INTERACTION_ACTIONS:
    COMMAND_FIELDS[_action] = COMMAND_FIELDS[_action] | {"mode", "target_url"}
def command_payload(action: str, body: dict[str, Any]) -> dict[str, Any]:
    if action not in COMPANION_COMMANDS:
        raise BrowserValidationError("This action is unavailable in the shared Chrome tab.", field="action")
    extras = set(body) - COMMAND_FIELDS[action] - {"action", "session_id"}
    if extras:
        raise BrowserValidationError("Caller code, selectors, policy and extra fields are unavailable.", field=sorted(extras)[0])
    result = {key: value for key, value in body.items() if key in COMMAND_FIELDS[action]}
    if action == "navigate":
        result["url"] = website_url(body.get("url"))
        if body.get("mode", "read_only") not in {"read_only", "interactive"}:
            raise BrowserValidationError("Choose a shared Chrome navigation mode.", field="mode")
        result.pop("mode", None)
    if action in INTERACTION_ACTIONS:
        if body.get("mode", "interactive") != "interactive":
            raise BrowserValidationError("Chrome actions require interactive mode.", field="mode")
        if "target_url" in result:
            result["target_url"] = website_url(result["target_url"])
        result.pop("mode", None)
        validate_interaction(action, result)
    if action in {"snapshot", "content.read", "scroll", "video.frame"}:
        validate_reading_action("content.read" if action == "snapshot" else action, result)
    if action == "scroll" and body.get("target", "auto") not in ("auto", "document"):
        raise BrowserValidationError("target must be auto or document.", field="target")
    if action == "content.collect":
        urls = body.get("urls")
        if not isinstance(urls, list) or not 1 <= len(urls) <= 2:
            raise BrowserValidationError("One or two source URLs are required.", field="urls")
        result["urls"] = [platform_url(url, expected_platform=platform_for_url(urls[0])) for url in urls]
        integer(body, "max_items", 1, 200)
        integer(body, "max_batches", 1, 40)
    if action == "video.analyze":
        integer(body, "video_index", 0, 199)
        integer(body, "frame_count", 1, 12)
        integer(body, "max_seconds", 1, 180)
        boolean(body, "include_audio")
        boolean(body, "save_evidence")
    if action == "screenshot":
        boolean(body, "full_page")
        if body.get("full_page"):
            raise BrowserValidationError("Chrome capture covers the visible shared tab, not a full-page stitch.", field="full_page")
    if action == "wait_for":
        if body.get("state", "domcontentloaded") not in ("domcontentloaded", "load"):
            raise BrowserValidationError("Chrome wait state must be domcontentloaded or load.", field="state")
        integer(body, "timeout_ms", 1, 15_000)
    return result


def integer(body: dict[str, Any], field: str, minimum: int, maximum: int) -> None:
    if field in body:
        value = body[field]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise BrowserValidationError(f"{field} must be an integer between {minimum} and {maximum}.", field=field)


def boolean(body: dict[str, Any], field: str) -> None:
    if field in body and not isinstance(body[field], bool):
        raise BrowserValidationError(f"{field} must be a boolean.", field=field)
