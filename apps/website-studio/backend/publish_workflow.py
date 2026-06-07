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


def managed_static_platform_binding(*, status: str, artifact_url: str) -> dict[str, object]:
    clean_status = str(status or "pending_generic_surface")
    return {
        "status": clean_status,
        "surface": "generic_static_hosting",
        "artifact_url": str(artifact_url or ""),
        "public_binding_ready": clean_status == "bound",
    }
