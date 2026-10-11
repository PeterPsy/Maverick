"""Bounded display metadata from authenticated Google profile responses."""

from urllib.parse import urlsplit


def google_picture_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return ""
    value = value.strip()
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        return ""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == "https" and parsed.hostname
                and parsed.hostname.endswith(".googleusercontent.com")
                and parsed.port in {None, 443} and not parsed.username
                and not parsed.password and not parsed.fragment):
            return value
    except ValueError:
        pass
    return ""
