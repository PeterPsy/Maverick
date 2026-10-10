"""Exact platform targets for a privately delegated browser login."""

import re
from urllib.parse import urlsplit


def is_platform_browser_target(url: str, origin: str | None, frame_host_suffix: str | None = None) -> bool:
    if not origin:
        return False
    try:
        target, platform = urlsplit(url), urlsplit(origin)
        if target.username or target.password or target.scheme != platform.scheme:
            return False
        if (target.port or (443 if target.scheme == "https" else 80)) != (platform.port or (443 if platform.scheme == "https" else 80)):
            return False
        if target.hostname == platform.hostname:
            return True
        suffix = frame_host_suffix or f".sidecars.{platform.hostname}"
        return bool(re.fullmatch(r"af-[0-9a-f]{24}" + re.escape(suffix), target.hostname or ""))
    except ValueError:
        return False
