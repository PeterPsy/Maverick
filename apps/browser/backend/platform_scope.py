"""Shared-source route policy; a Chrome lease stays on its user-selected platform."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from errors import BrowserValidationError


PLATFORMS = json.loads((Path(__file__).resolve().parents[1] / "companion/platforms.json").read_text())
BLOCKED = frozenset({"accounts", "account", "direct", "api", "challenge", "checkpoint", "oauth", "settings", "messages", "messaging", "login", "login.php", "logout", "signin", "signup", "security", "notifications", "compose", "intent", "dialogs", "payment", "payments", "trade", "trading"})


def platform_for_url(value: str) -> str | None:
    try:
        host = urlsplit(value).hostname
    except ValueError:
        return None
    return next((key for key, spec in PLATFORMS.items() if host in spec["hosts"]), None)


def platform_url(value: object, *, expected_platform: str | None = None) -> str:
    if not isinstance(value, str) or len(value) > 2048 or value != value.strip() or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        raise BrowserValidationError("A supported platform HTTPS URL is required.", field="url")
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme == "https" and parsed.port in (None, 443) and not parsed.username and not parsed.password
    except ValueError:
        valid = False
    platform = platform_for_url(value)
    if not valid or not platform or expected_platform and platform != expected_platform:
        raise BrowserValidationError("Navigation must remain on the platform explicitly shared by the user.", field="url")
    parts = parsed.path.strip("/").split("/")
    if "%" in parsed.path or "//" in parsed.path or any(p in {".", ".."} or p.lower() in BLOCKED or p.lower().startswith("security-check") for p in parts):
        raise BrowserValidationError("Credentials, messages, challenges and settings are outside read-only scope.", field="url")
    spec = PLATFORMS[platform]
    if not any(re.fullmatch(pattern, parsed.path) for pattern in spec["paths"]):
        raise BrowserValidationError("This route is outside the platform's read-only scope.", field="url")
    try:
        pairs = [(k, v) for k, v in parse_qsl(parsed.query, max_num_fields=30) if k in spec["query_keys"]]
    except ValueError:
        raise BrowserValidationError("The platform query exceeds its read budget.", field="url") from None
    if any(len(v) > 500 or any(ord(c) < 32 for c in v) for _, v in pairs):
        raise BrowserValidationError("The platform query exceeds its read budget.", field="url")
    path = parsed.path if parsed.path.endswith("/") or re.search(r"\.(html|php)$",parts[-1]) else parsed.path + "/"
    host = parsed.hostname
    if platform == "twitter":
        host = "x.com"
    if platform == "reddit":
        host = "www.reddit.com"
    if platform == "youtube" and host == "youtu.be":
        pairs = [("v",parts[0])]
        host,path = "www.youtube.com","/watch"
    elif platform == "youtube" and path == "/watch/":
        host,path = "www.youtube.com","/watch"
    return urlunsplit(("https", host, path, urlencode(pairs), ""))
