"""Fixed Chrome observation inputs and Instagram navigation scope."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from errors import BrowserValidationError
from reading_validation import validate_reading_action


COMPANION_COMMANDS = frozenset({
    "navigate", "snapshot", "content.read", "scroll", "screenshot", "video.frame",
    "video.analyze", "instagram.collect", "tabs", "wait_for",
})
COMMAND_FIELDS = {
    "navigate": {"url", "mode"},
    "snapshot": {"max_chars", "max_items"},
    "content.read": {"max_chars", "max_items"},
    "scroll": {"direction", "pixels", "steps", "settle_ms", "target"},
    "screenshot": {"full_page"},
    "video.frame": {"video_index", "time_seconds"},
    "video.analyze": {"video_index", "frame_count", "max_seconds", "include_audio", "save_evidence"},
    "instagram.collect": {"username", "max_items", "max_batches", "include_reels"},
    "tabs": set(),
    "wait_for": {"state", "timeout_ms"},
}
USERNAME = re.compile(r"[A-Za-z0-9._]{1,30}\Z")
SHORTCODE = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
RESERVED = frozenset({"accounts", "direct", "api", "challenge", "checkpoint", "oauth", "settings"})


def instagram_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2048 or value != value.strip() or any(c.isspace() for c in value):
        raise BrowserValidationError("An Instagram profile, post or Reel URL is required.", field="url")
    try:
        parsed = urlsplit(value)
        valid_host = parsed.hostname == "www.instagram.com" and parsed.port in (None, 443)
    except ValueError:
        valid_host = False
    if not valid_host or parsed.scheme != "https" or parsed.username or parsed.password:
        raise BrowserValidationError("Chrome navigation is limited to https://www.instagram.com.", field="url")
    segments = parsed.path.strip("/").split("/")
    valid = (
        len(segments) == 1 and USERNAME.fullmatch(segments[0]) and segments[0].lower() not in RESERVED
        or len(segments) == 2 and segments[0] in {"p", "reel"} and SHORTCODE.fullmatch(segments[1])
        or len(segments) == 2 and USERNAME.fullmatch(segments[0])
        and segments[0].lower() not in RESERVED and segments[1] == "reels"
    )
    if not valid or "//" in parsed.path or "\\" in value or "%" in parsed.path or any(s in {".", ".."} for s in segments):
        raise BrowserValidationError("This Instagram route is outside read-only navigation scope.", field="url")
    return urlunsplit(("https", "www.instagram.com", "/" + "/".join(segments) + "/", "", ""))


def command_payload(action: str, body: dict[str, Any]) -> dict[str, Any]:
    if action not in COMPANION_COMMANDS:
        raise BrowserValidationError("This action is unavailable in the shared Chrome tab.", field="action")
    extras = set(body) - COMMAND_FIELDS[action] - {"action", "session_id"}
    if extras:
        raise BrowserValidationError("Caller code, selectors, policy and extra fields are unavailable.", field=sorted(extras)[0])
    result = {key: value for key, value in body.items() if key in COMMAND_FIELDS[action]}
    if action == "navigate":
        result["url"] = instagram_url(body.get("url"))
        if body.get("mode", "read_only") != "read_only":
            raise BrowserValidationError("Shared Chrome supports read_only mode.", field="mode")
        result.pop("mode", None)
    if action in {"snapshot", "content.read", "scroll", "video.frame"}:
        validate_reading_action("content.read" if action == "snapshot" else action, result)
    if action == "scroll" and body.get("target", "auto") not in ("auto", "document"):
        raise BrowserValidationError("target must be auto or document.", field="target")
    if action == "instagram.collect":
        username = body.get("username")
        if not isinstance(username, str) or not USERNAME.fullmatch(username) or username.lower() in RESERVED:
            raise BrowserValidationError("A valid Instagram username is required.", field="username")
        result["username"] = username
        integer(body, "max_items", 1, 200)
        integer(body, "max_batches", 1, 40)
        boolean(body, "include_reels")
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
