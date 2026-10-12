"""App-owned public endpoint dependencies; declarations grant no route access."""

from urllib.parse import urlsplit, unquote
import re

from core.apps.errors import AppContractValidationError
from core.apps.models import AppInstallationDeclaration, AppPublicEndpointDeclaration


def parse_installation(payload: dict, app_id: str) -> AppInstallationDeclaration:
    if not isinstance(payload, dict) or set(payload) - {"public_endpoints"}:
        raise AppContractValidationError("Invalid installation declaration")
    entries = payload.get("public_endpoints", [])
    if not isinstance(entries, list) or len(entries) > 32:
        raise AppContractValidationError("Invalid public endpoint declarations")
    endpoints, identifiers = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"id", "label", "kind", "path", "provider_url", "requires_registration"}:
            raise AppContractValidationError("Invalid installation public endpoint")
        identifier = entry.get("id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier) or identifier in identifiers:
            raise AppContractValidationError("Invalid or duplicate public endpoint id")
        identifiers.add(identifier)
        kind, path = entry.get("kind"), entry.get("path", "")
        if kind not in {"oauth_redirect", "webhook", "public_url"}:
            raise AppContractValidationError("Invalid public endpoint kind")
        decoded = unquote(path) if isinstance(path, str) else ""
        if (not isinstance(path, str) or len(path) > 256 or "?" in path or "#" in path or "\\" in decoded
                or any(part in {".", ".."} for part in decoded.split("/"))
                or path.count("{app_id}") != 1 or not re.fullmatch(r"/[A-Za-z0-9{}/._~-]+", path)
                or not any(path == prefix or path.startswith(prefix + "/")
                           for prefix in ("/api/apps/{app_id}", "/apps/{app_id}", "/app/{app_id}"))):
            raise AppContractValidationError("Public endpoint path must belong to its app")
        label = entry.get("label", identifier)
        if not isinstance(label, str) or not label.strip() or len(label) > 128:
            raise AppContractValidationError("Invalid public endpoint label")
        provider = entry.get("provider_url", "")
        if not isinstance(provider, str) or len(provider) > 512:
            raise AppContractValidationError("Invalid provider console link")
        try:
            parsed = urlsplit(provider)
        except ValueError:
            raise AppContractValidationError("Invalid provider console link") from None
        if provider and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            raise AppContractValidationError("Provider console links require HTTPS")
        required = entry.get("requires_registration", kind != "public_url")
        if not isinstance(required, bool):
            raise AppContractValidationError("requires_registration must be boolean")
        endpoints.append(AppPublicEndpointDeclaration(identifier, label, kind, path, provider, required))
    return AppInstallationDeclaration(endpoints)
