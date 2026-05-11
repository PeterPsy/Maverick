"""File-backed documentation sources for Docs Studio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_readmes import build_apps_section


SCHEMA_VERSION = "1"
APP_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = APP_ROOT / "docs"

DEFAULT_SITE = {
    "name": "Maverick Docs",
    "logo": "MD",
    "accent": "#4f46e5",
    "tagline": "Curated Maverick core, workspace, and app contract documentation.",
}

DEFAULT_VIEW_STATE = {
    "query": "",
    "section_id": None,
    "custom_page_ids": [],
}


def default_docs_state() -> dict[str, object]:
    """Return lightweight workspace-owned Docs Studio state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "site": dict(DEFAULT_SITE),
        "view_state": dict(DEFAULT_VIEW_STATE),
    }


def _read_manifest(docs_root: Path = DOCS_ROOT) -> dict[str, Any]:
    path = docs_root / "manifest.json"
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "sections": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {"schema_version": SCHEMA_VERSION, "sections": []}


def curated_sections(docs_root: Path = DOCS_ROOT) -> list[dict[str, object]]:
    """Load curated documentation sections from Markdown files."""
    manifest = _read_manifest(docs_root)
    sections: list[dict[str, object]] = []
    for section in manifest.get("sections", []):
        if not isinstance(section, dict):
            continue
        pages = []
        for page in section.get("pages", []):
            if not isinstance(page, dict):
                continue
            source_path = str(page.get("source_path") or "")
            body_path = (docs_root / source_path).resolve(strict=False)
            try:
                body_path.relative_to(docs_root.resolve(strict=False))
            except ValueError:
                continue
            body = body_path.read_text(encoding="utf-8") if body_path.exists() else ""
            pages.append({
                "id": str(page.get("id") or body_path.stem),
                "title": str(page.get("title") or body_path.stem.replace("-", " ").title()),
                "icon": str(page.get("icon") or "doc"),
                "summary": str(page.get("summary") or ""),
                "body": body,
                "source_path": f"apps/docs-studio/docs/{source_path}",
                "updated_at": "",
            })
        sections.append({
            "id": str(section.get("id") or "docs"),
            "title": str(section.get("title") or "Docs"),
            "pages": pages,
        })
    return sections


def curated_core_docs_state(include_apps: bool = False) -> dict[str, object]:
    """Return composed docs for compatibility with existing hooks and tests."""
    state = default_docs_state()
    state["sections"] = curated_sections()
    if include_apps:
        state["sections"].append(build_apps_section())
    return state
