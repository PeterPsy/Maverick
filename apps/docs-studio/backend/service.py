"""Service logic for Docs Studio."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
from uuid import uuid4

from core.app_sdk.runtime import AppEntrypointPayload
from core.app_sdk.storage import read_json_state, write_json_state
from app_readmes import build_apps_section
from seed_docs import curated_sections, default_docs_state


STATE_FILE = "state.json"
SCHEMA_VERSION = "1"
CUSTOM_MANIFEST = "pages/manifest.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def default_state() -> dict[str, object]:
    """Return lightweight workspace-owned configuration state."""
    return default_docs_state()


def _without_composed_sections(state: dict[str, object]) -> tuple[dict[str, object], bool]:
    normalized = deepcopy(state)
    if "sections" not in normalized:
        return normalized, False
    normalized.pop("sections", None)
    return normalized, True


def _workspace_root(payload: AppEntrypointPayload) -> Path | None:
    if payload.workspace_root:
        return Path(payload.workspace_root)
    data_root = Path(payload.data_root).resolve()
    if data_root.parent.name == "data":
        return data_root.parent.parent
    return None


def _read_custom_manifest(payload: AppEntrypointPayload) -> dict[str, object]:
    path = Path(payload.data_root) / CUSTOM_MANIFEST
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "sections": []}
    payload_json = read_json_state(payload.data_root, CUSTOM_MANIFEST, {"schema_version": SCHEMA_VERSION, "sections": []})
    return payload_json if isinstance(payload_json, dict) else {"schema_version": SCHEMA_VERSION, "sections": []}


def _write_custom_manifest(payload: AppEntrypointPayload, manifest: dict[str, object]) -> None:
    manifest["schema_version"] = SCHEMA_VERSION
    write_json_state(payload.data_root, CUSTOM_MANIFEST, manifest)


def _custom_page_path(payload: AppEntrypointPayload, section_id: str, page_id: str) -> Path:
    safe_section = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in section_id)
    safe_page = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in page_id)
    root = (Path(payload.data_root) / "pages").resolve(strict=False)
    path = (root / safe_section / f"{safe_page}.md").resolve(strict=False)
    path.relative_to(root)
    return path


def _custom_sections(payload: AppEntrypointPayload) -> list[dict[str, object]]:
    manifest = _read_custom_manifest(payload)
    sections: list[dict[str, object]] = []
    for section in manifest.get("sections", []):
        if not isinstance(section, dict):
            continue
        pages = []
        for page in section.get("pages", []):
            if not isinstance(page, dict):
                continue
            source_path = str(page.get("source_path") or "")
            body_path = (Path(payload.data_root) / source_path).resolve(strict=False)
            try:
                body_path.relative_to(Path(payload.data_root).resolve(strict=False))
            except ValueError:
                continue
            body = body_path.read_text(encoding="utf-8") if body_path.exists() else ""
            pages.append({
                "id": str(page.get("id") or body_path.stem),
                "title": str(page.get("title") or "Untitled page"),
                "icon": str(page.get("icon") or "doc"),
                "summary": str(page.get("summary") or "Workspace documentation page."),
                "body": body,
                "source_path": source_path,
                "updated_at": str(page.get("updated_at") or ""),
            })
        sections.append({
            "id": str(section.get("id") or "workspace"),
            "title": str(section.get("title") or "Workspace"),
            "pages": pages,
        })
    return sections


def _merge_sections(base_sections: list[dict[str, object]], extra_sections: list[dict[str, object]]) -> list[dict[str, object]]:
    merged = deepcopy(base_sections)
    by_id = {section.get("id"): section for section in merged}
    for section in extra_sections:
        section_id = section.get("id")
        existing = by_id.get(section_id)
        if existing is None:
            merged.append(section)
            by_id[section_id] = section
            continue
        pages = existing.setdefault("pages", [])
        if isinstance(pages, list):
            pages.extend(section.get("pages", []) if isinstance(section.get("pages"), list) else [])
    return merged


def _composed_state(payload: AppEntrypointPayload, state: dict[str, object]) -> dict[str, object]:
    composed, _ = _without_composed_sections(state)
    sections = _merge_sections(curated_sections(), _custom_sections(payload))
    workspace_root = _workspace_root(payload)
    sections.append(build_apps_section(workspace_root=workspace_root) if workspace_root else build_apps_section())
    composed["sections"] = sections
    return composed


def load_state(payload: AppEntrypointPayload) -> dict[str, object]:
    state_path = Path(payload.data_root) / STATE_FILE
    state = read_json_state(payload.data_root, STATE_FILE, default_state())
    if not state_path.exists() or not state:
        state = default_state()
        save_state(payload, state)
    state, changed = _without_composed_sections(state)
    if changed:
        save_state(payload, state)
    return state


def save_state(payload: AppEntrypointPayload, state: dict[str, object]) -> dict[str, object]:
    state, _ = _without_composed_sections(state)
    state["schema_version"] = SCHEMA_VERSION
    write_json_state(payload.data_root, STATE_FILE, state)
    return state


def update_site(payload: AppEntrypointPayload, updates: dict[str, object]) -> dict[str, object]:
    state = load_state(payload)
    site = state.setdefault("site", {})
    if not isinstance(site, dict):
        site = {}
        state["site"] = site
    for key in ("name", "logo", "accent", "tagline"):
        value = updates.get(key)
        if isinstance(value, str) and value.strip():
            site[key] = value.strip()
    save_state(payload, state)
    return _composed_state(payload, state)


def create_page(payload: AppEntrypointPayload, body: dict[str, object]) -> dict[str, object]:
    section_id = str(body.get("section_id") or "getting-started")
    title = str(body.get("title") or "Untitled page").strip() or "Untitled page"
    page_id = _new_id("page")
    body_text = str(body.get("body") or f"# {title}\n\nStart writing here.")
    path = _custom_page_path(payload, section_id, page_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body_text.rstrip() + "\n", encoding="utf-8")
    page = {
        "id": page_id,
        "title": title,
        "icon": str(body.get("icon") or "doc"),
        "summary": str(body.get("summary") or "New documentation page."),
        "source_path": path.relative_to(Path(payload.data_root)).as_posix(),
        "updated_at": _now(),
    }
    manifest = _read_custom_manifest(payload)
    sections = manifest.setdefault("sections", [])
    if not isinstance(sections, list):
        sections = []
        manifest["sections"] = sections
    section = next((item for item in sections if isinstance(item, dict) and item.get("id") == section_id), None)
    if section is None:
        section = {"id": section_id, "title": section_id.replace("-", " ").title(), "pages": []}
        sections.append(section)
    pages = section.setdefault("pages", [])
    if isinstance(pages, list):
        pages.append(page)
    _write_custom_manifest(payload, manifest)
    page_with_body = {**page, "body": body_text.rstrip() + "\n"}
    return {"state": _composed_state(payload, load_state(payload)), "page": page_with_body}


def update_page(payload: AppEntrypointPayload, body: dict[str, object]) -> dict[str, object]:
    page_id = str(body.get("page_id") or "")
    if not page_id:
        raise ValueError("page_id is required.")
    manifest = _read_custom_manifest(payload)
    page = None
    for section in manifest.get("sections", []):
        if not isinstance(section, dict):
            continue
        for candidate in section.get("pages", []):
            if isinstance(candidate, dict) and candidate.get("id") == page_id:
                page = candidate
                break
        if page is not None:
            break
    if page is None:
        raise ValueError(f"Page `{page_id}` is not a workspace-editable page.")
    for key in ("title", "summary", "icon"):
        value = body.get(key)
        if isinstance(value, str):
            page[key] = value
    body_value = body.get("body")
    if isinstance(body_value, str):
        source_path = str(page.get("source_path") or "")
        path = (Path(payload.data_root) / source_path).resolve(strict=False)
        path.relative_to(Path(payload.data_root).resolve(strict=False))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body_value.rstrip() + "\n", encoding="utf-8")
    page["updated_at"] = _now()
    _write_custom_manifest(payload, manifest)
    return {"state": _composed_state(payload, load_state(payload)), "page": deepcopy(page)}


def reference_manifest() -> dict[str, object]:
    return {
        "entity_types": [
            {
                "entity_type": "doc_page",
                "display_name": "Documentation page",
                "searchable": True,
                "resolvable": True,
                "summarizable": True,
                "deep_link_supported": True,
            }
        ]
    }


def _iter_pages(state: dict[str, object]) -> list[dict[str, object]]:
    pages: list[dict[str, object]] = []
    for section in state.get("sections", []):
        if not isinstance(section, dict):
            continue
        for page in section.get("pages", []):
            if isinstance(page, dict):
                pages.append({
                    "section_id": section.get("id"),
                    "section_title": section.get("title"),
                    **page,
                })
    return pages


def _coerce_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _query_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9][a-z0-9_-]*", query.lower()) if term]


def _page_matches_filters(page: dict[str, object], filters: dict[str, object]) -> bool:
    section_id = filters.get("section_id")
    if isinstance(section_id, str) and section_id and page.get("section_id") != section_id:
        return False
    source_app_id = filters.get("source_app_id")
    if isinstance(source_app_id, str) and source_app_id and page.get("source_app_id") != source_app_id:
        return False
    return True


def _score_page(page: dict[str, object], terms: list[str]) -> int:
    if not terms:
        return 1
    title = str(page.get("title") or "").lower()
    summary = str(page.get("summary") or "").lower()
    body = str(page.get("body") or "").lower()
    score = 0
    for term in terms:
        if term in title:
            score += 12
        if term in summary:
            score += 6
        if term in body:
            score += 2
    return score


def _page_excerpt(page: dict[str, object], terms: list[str], max_chars: int) -> str:
    body = str(page.get("body") or "")
    if not body:
        return str(page.get("summary") or "")[:max_chars]
    lower_body = body.lower()
    match_at = -1
    for term in terms:
        match_at = lower_body.find(term)
        if match_at >= 0:
            break
    if match_at < 0:
        return body[:max_chars].strip()
    start = max(0, match_at - max_chars // 3)
    end = min(len(body), start + max_chars)
    excerpt = body[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(body):
        excerpt = excerpt + "..."
    return excerpt


def _compact_page(page: dict[str, object], *, include_excerpt: bool = False, terms: list[str] | None = None, max_chars: int = 500) -> dict[str, object]:
    payload = {
        "app_id": "docs-studio",
        "entity_type": "doc_page",
        "entity_id": page.get("id"),
        "page_id": page.get("id"),
        "title": page.get("title"),
        "summary": page.get("summary"),
        "section_id": page.get("section_id"),
        "section_title": page.get("section_title"),
        "source_path": page.get("source_path"),
        "source_app_id": page.get("source_app_id"),
        "deep_link": f"/app/docs-studio/pages/{page.get('id')}",
    }
    if include_excerpt:
        payload["excerpt"] = _page_excerpt(page, terms or [], max_chars)
    return payload


def docs_manifest(payload: AppEntrypointPayload, options: dict[str, object] | None = None) -> dict[str, object]:
    """Return a compact table of contents without page bodies."""
    options = options or {}
    state = _composed_state(payload, load_state(payload))
    requested_section_id = options.get("section_id")
    include_pages = bool(options.get("include_pages", True))
    sections = []
    page_count = 0
    for section in state.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or "")
        if isinstance(requested_section_id, str) and requested_section_id and section_id != requested_section_id:
            continue
        pages = [page for page in section.get("pages", []) if isinstance(page, dict)]
        page_count += len(pages)
        section_payload: dict[str, object] = {
            "section_id": section_id,
            "title": section.get("title"),
            "page_count": len(pages),
        }
        if include_pages:
            section_payload["pages"] = [
                {
                    "page_id": page.get("id"),
                    "title": page.get("title"),
                    "summary": page.get("summary"),
                    "source_app_id": page.get("source_app_id"),
                }
                for page in pages
            ]
        sections.append(section_payload)
    return {
        "manifest": {
            "section_count": len(sections),
            "page_count": page_count,
            "sections": sections,
        }
    }


def docs_search(payload: AppEntrypointPayload, options: dict[str, object] | None = None) -> dict[str, object]:
    """Search composed docs with optional section and app-source filters."""
    options = options or {}
    query = str(options.get("query") or "").strip()
    terms = _query_terms(query)
    limit = _coerce_int(options.get("limit"), 10, minimum=1, maximum=50)
    max_chars = _coerce_int(options.get("max_chars"), 600, minimum=120, maximum=2000)
    state = _composed_state(payload, load_state(payload))
    ranked = []
    for page in _iter_pages(state):
        if not _page_matches_filters(page, options):
            continue
        score = _score_page(page, terms)
        if terms and score <= 0:
            continue
        ranked.append((score, str(page.get("title") or ""), page))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return {
        "query": query,
        "results": [
            {
                **_compact_page(page, include_excerpt=True, terms=terms, max_chars=max_chars),
                "score": score,
            }
            for score, _title, page in ranked[:limit]
        ],
    }


def docs_read(payload: AppEntrypointPayload, options: dict[str, object] | None = None) -> dict[str, object]:
    """Read one documentation page by page id, with optional body truncation."""
    options = options or {}
    page_id = str(options.get("page_id") or options.get("entity_id") or "").strip()
    if not page_id:
        raise ValueError("page_id is required.")
    max_chars = _coerce_int(options.get("max_chars"), 12000, minimum=500, maximum=50000)
    state = _composed_state(payload, load_state(payload))
    for page in _iter_pages(state):
        if page.get("id") != page_id:
            continue
        body = str(page.get("body") or "")
        truncated_body = body[:max_chars]
        return {
            "page": {
                **_compact_page(page),
                "body": truncated_body,
                "body_format": "markdown",
                "body_char_count": len(body),
                "truncated": len(truncated_body) < len(body),
            }
        }
    return {"page": None}


def reference_search(payload: AppEntrypointPayload, query: str = "") -> dict[str, object]:
    return {"results": docs_search(payload, {"query": query, "limit": 20})["results"]}


def reference_resolve(payload: AppEntrypointPayload, entity_id: str) -> dict[str, object]:
    state = _composed_state(payload, load_state(payload))
    for page in _iter_pages(state):
        if page.get("id") == entity_id:
            return {"entity": _compact_page(page)}
    return {"entity": None}


def reference_summarize(payload: AppEntrypointPayload, entity_id: str) -> dict[str, object]:
    read = docs_read(payload, {"page_id": entity_id, "max_chars": 1200}).get("page")
    if not isinstance(read, dict):
        return {"summary": None}
    return {
        "summary": {
            "title": read.get("title"),
            "text": read.get("summary") or str(read.get("body") or "")[:500],
            "source": {
                "app_id": "docs-studio",
                "entity_type": "doc_page",
                "entity_id": read.get("entity_id"),
            },
        }
    }


def view_filter(payload: AppEntrypointPayload) -> dict[str, object]:
    state = load_state(payload)
    return {"view_state": state.get("view_state") or {}}


def set_view_filter(payload: AppEntrypointPayload, updates: dict[str, object]) -> dict[str, object]:
    state = load_state(payload)
    view_state = state.setdefault("view_state", {})
    if not isinstance(view_state, dict):
        view_state = {}
        state["view_state"] = view_state
    view_state["query"] = str(updates.get("query") or "")
    section_id = updates.get("section_id")
    view_state["section_id"] = section_id if isinstance(section_id, str) and section_id else None
    save_state(payload, state)
    return {"view_state": view_state}


def set_custom_view(payload: AppEntrypointPayload, page_ids: list[object]) -> dict[str, object]:
    state = load_state(payload)
    view_state = state.setdefault("view_state", {})
    if not isinstance(view_state, dict):
        view_state = {}
        state["view_state"] = view_state
    view_state["custom_page_ids"] = [str(page_id) for page_id in page_ids if str(page_id)]
    save_state(payload, state)
    return {"view_state": view_state}


def clear_custom_view(payload: AppEntrypointPayload) -> dict[str, object]:
    state = load_state(payload)
    view_state = state.setdefault("view_state", {})
    if not isinstance(view_state, dict):
        view_state = {}
        state["view_state"] = view_state
    view_state["custom_page_ids"] = []
    save_state(payload, state)
    return {"view_state": view_state}


def status_payload(payload: AppEntrypointPayload) -> dict[str, object]:
    """Return a health/status payload for this app."""
    state = _composed_state(payload, load_state(payload))
    sections = state.get("sections", [])
    page_count = 0
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, dict) and isinstance(section.get("pages"), list):
                page_count += len(section["pages"])
    return {
        "app_id": "docs-studio",
        "workspace_id": payload.workspace_id,
        "status": "ready",
        "schema_version": state.get("schema_version"),
        "page_count": page_count,
    }


def state_payload(payload: AppEntrypointPayload) -> dict[str, object]:
    return {"state": _composed_state(payload, load_state(payload))}


def navigation_payload(payload: AppEntrypointPayload) -> dict[str, object]:
    """Return a compact state shape for sidebar navigation."""
    state = _composed_state(payload, load_state(payload))
    sections = []
    for section in state.get("sections", []):
        if not isinstance(section, dict):
            continue
        pages = []
        for page in section.get("pages", []):
            if not isinstance(page, dict):
                continue
            pages.append({
                "id": page.get("id"),
                "title": page.get("title"),
                "icon": page.get("icon"),
                "summary": page.get("summary"),
                "source_app_id": page.get("source_app_id"),
                "updated_at": page.get("updated_at"),
            })
        sections.append({
            "id": section.get("id"),
            "title": section.get("title"),
            "pages": pages,
        })
    return {
        "state": {
            "schema_version": state.get("schema_version"),
            "site": state.get("site"),
            "view_state": state.get("view_state") or {},
            "sections": sections,
        }
    }
