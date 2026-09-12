"""Normalize portfolio URLs and identify explicit Instagram profiles."""

from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlsplit


URL_PATTERN = re.compile(
    r"""(?ix)
    (?<![@\w])
    (
      (?:(?:https?://)|(?:www\.))[^\s<>\"'`]+
      |
      (?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}
      (?:/[^\s<>\"'`]*)?
    )
    """
)
INSTAGRAM_RESERVED_PATHS = {
    "about", "accounts", "challenge", "developer", "direct", "explore",
    "legal", "p", "reel", "reels", "share", "stories", "tv", "web",
}
INSTAGRAM_USERNAME = re.compile(r"^[a-z0-9._]{1,30}$", re.IGNORECASE)


def _clean_url(raw: str) -> str:
    candidate = raw.strip().rstrip(".,;:!?")
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while candidate.endswith(closing) and candidate.count(closing) > candidate.count(opening):
            candidate = candidate[:-1]
    if not re.match(r"^https?://", candidate, re.IGNORECASE):
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").lower()
    if "." not in hostname or any(character.isspace() for character in candidate):
        return ""
    return candidate


def _dedupe(urls: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for url in urls:
        parsed = urlsplit(url)
        key = f"{(parsed.hostname or '').lower()}{parsed.path.rstrip('/')}?{parsed.query}".lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(url)
    return result[:50]


def extract_urls(raw: Any) -> list[str]:
    """Extract separate, usable web links from free-form text or an array."""
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    found: list[str] = []
    for value in values[:50]:
        if isinstance(value, dict):
            value = value.get("url", "")
        for match in URL_PATTERN.finditer(str(value or "")):
            cleaned = _clean_url(match.group(1))
            if cleaned:
                found.append(cleaned)
    return _dedupe(found)


def instagram_profile_url(url: str) -> str:
    """Return a canonical profile URL, excluding Instagram content/system links."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    if hostname != "instagram.com":
        return ""
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) != 1:
        return ""
    username = segments[0]
    if username.lower() in INSTAGRAM_RESERVED_PATHS or not INSTAGRAM_USERNAME.fullmatch(username):
        return ""
    return f"https://www.instagram.com/{username}/"


def extract_instagram_profiles(*values: Any) -> list[str]:
    profiles = (instagram_profile_url(url) for value in values for url in extract_urls(value))
    return _dedupe(profile for profile in profiles if profile)
