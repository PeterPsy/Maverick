"""Publish workflow helpers for Website Studio."""

from __future__ import annotations

from safety import slugify


def working_branch_for_site(site: dict[str, object], request: dict[str, object] | None = None) -> str:
    site_id = str(site.get("id") or "site")
    slug = publish_request_slug(request) if request else str(site.get("slug") or site_id)
    return f"maverick/{site_id}/{slug}"


def publish_request_slug(request: dict[str, object] | None) -> str:
    if not request:
        return "change"
    request_id = str(request.get("id") or "").strip()
    if request_id:
        return slugify(request_id) or "change"
    summary = str(request.get("diff_summary") or "").strip()
    return slugify(summary) or "change"


def managed_static_platform_binding(
    *,
    status: str,
    artifact_url: str,
    public_url: str = "",
    custom_domain: str = "",
    certificate_status: str = "",
    cache_policy: str = "",
    cdn_status: str = "",
    verification_status: str = "",
) -> dict[str, object]:
    clean_status = str(status or "pending_generic_surface")
    clean_public_url = str(public_url or "")
    return {
        "status": clean_status,
        "surface": "generic_static_hosting",
        "artifact_url": str(artifact_url or ""),
        "public_url": clean_public_url,
        "custom_domain": str(custom_domain or ""),
        "certificate_status": str(certificate_status or ""),
        "cache_policy": str(cache_policy or ""),
        "cdn_status": str(cdn_status or ""),
        "verification_status": str(verification_status or ""),
        "public_binding_ready": clean_status == "bound" and bool(clean_public_url),
        "missing_requirements": _managed_static_missing_requirements(clean_status, clean_public_url),
    }


def _managed_static_missing_requirements(status: str, public_url: str) -> list[str]:
    if status == "bound" and public_url:
        return []
    return [
        "generic static hosting surface",
        "stable public URL",
        "domain/certificate binding",
        "external HTTP verification",
    ]
