"""Closed static-bundle and public URL policy (no platform dependencies)."""
import re
from urllib.parse import unquote, urlsplit

from .errors import AppError

MAX_ZIP = 2 * 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_FILES = 512
MAX_RATIO = 100
PLAN_TTL = 900
MAX_APPS = 100
MAX_RELEASES = 1000
MIME = {
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".json": "application/json",
    ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
    ".avif": "image/avif", ".woff": "font/woff", ".woff2": "font/woff2",
    ".ttf": "font/ttf", ".otf": "font/otf", ".mp4": "video/mp4",
    ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".pdf": "application/pdf",
}
PRIVATE_NAMES = {"package.json", "package-lock.json", "tsconfig.json", "composer.json", "composer.lock"}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; font-src 'self'; connect-src 'none'; worker-src 'none'; "
       "object-src 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'self'")
HEADERS = {
    "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache, must-revalidate",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def identifier(value, prefix="", length=32):
    value = str(value or "")
    if not re.fullmatch(re.escape(prefix) + f"[a-f0-9]{{{length}}}", value):
        raise AppError("invalid_identifier")
    return value


def digest(value):
    return identifier(value, length=64)


def artifact_path(value):
    if not isinstance(value, str) or not value or len(value) > 240:
        raise AppError("invalid_artifact_path")
    if any(ord(c) < 32 or ord(c) > 126 for c in value) or any(c in value for c in "\\%?#:"):
        raise AppError("invalid_artifact_path")
    parts = value.split("/")
    if any(not p or p.startswith(".") or p in PRIVATE_NAMES for p in parts):
        raise AppError("invalid_artifact_path")
    if not re.fullmatch(r"[A-Za-z0-9_./@+ -]+", value):
        raise AppError("invalid_artifact_path")
    suffix = "." + parts[-1].rsplit(".", 1)[-1].lower()
    if suffix not in MIME:
        raise AppError("unsupported_mime")
    return value, MIME[suffix]


def domain_name(value):
    value = str(value or "").lower()
    if len(value) > 180 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
        raise AppError("invalid_public_domain")
    if "." not in value or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in value.split(".")):
        raise AppError("invalid_public_domain")
    return value


def canonical_host(value, domain):
    if not isinstance(value, str) or value != value.strip():
        raise AppError("invalid_host", 404)
    host = value.lower()
    suffix = "." + domain_name(domain)
    if not host.endswith(suffix) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host[:-len(suffix)]):
        raise AppError("invalid_host", 404)
    return host


def canonical_path(value):
    if (not isinstance(value, str) or not value.startswith("/") or value.startswith("//") or len(value) > 2048
            or "#" in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise AppError("invalid_path")
    raw = urlsplit(value).path
    if re.search(r"%(?:2f|5c|2e|25)", raw, re.I) or re.search(r"%(?![a-fA-F0-9]{2})", raw):
        raise AppError("invalid_path")
    path = unquote(raw, errors="strict")
    if "\\" in path or "%" in path or "//" in path or any(ord(c) < 32 for c in path):
        raise AppError("invalid_path")
    if any(p in {".", ".."} for p in path.split("/")):
        raise AppError("invalid_path")
    return path


def slug(value):
    result = re.sub(r"[^a-z0-9]+", "-", str(value or "site").lower()).strip("-")[:25].rstrip("-")
    return result or "site"
