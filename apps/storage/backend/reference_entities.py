"""Reference entity payloads for Storage files and folders."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, unquote

from errors import StorageValidationError
from inventory import resolve_file_record
from store import catalog_files_payload, storage_root_for_role


REFERENCE_MANIFEST = {
    "app_id": "storage",
    "schema_version": "1",
    "entity_types": [
        {
            "entity_type": "file",
            "display_name": "Workspace File",
            "id_stability": "stable",
            "searchable": True,
            "resolvable": True,
            "summarizable": True,
            "deep_link_supported": True,
        },
        {
            "entity_type": "folder",
            "display_name": "Storage Folder",
            "id_stability": "path",
            "searchable": True,
            "resolvable": True,
            "summarizable": True,
            "deep_link_supported": True,
        },
    ],
}

STORAGE_FILE_ROLES = {"uploaded", "generated"}
UPLOAD_BUCKET_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def reference_search_payload(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    query = str(body.get("query") or "")
    entity_type = str(body.get("entity_type") or "file").strip() or "file"
    limit = _optional_positive_int(body, "limit", maximum=50) or 10
    if entity_type == "folder":
        folders = _rank_folder_records(
            [
                record
                for record in _folder_records(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)
                if _folder_matches_query(record, query)
            ],
            query=query,
        )
        return {"results": [_folder_reference(item) for item in folders[:limit]]}
    if entity_type != "file":
        return {"results": []}
    catalog_limit = None if query.strip() else limit
    catalog = catalog_files_payload(
        data_root=data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
        query="",
        offset=0,
        limit=catalog_limit,
    )
    files = _rank_file_records(catalog["files"], query=query)
    return {"results": [_file_reference(item) for item in files[:limit]]}


def reference_resolve_payload(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    entity_type = str(body.get("entity_type") or "file").strip() or "file"
    entity_id = str(body.get("entity_id") or "").strip()
    if entity_type == "folder":
        record = _resolve_folder_record(
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            entity_id=entity_id,
        )
        item = _folder_reference(record) if record is not None else None
        if item is None:
            return {"exists": False, "app_id": "storage", "entity_type": "folder", "entity_id": entity_id}
        return {"exists": True, **item}
    if entity_type != "file":
        return {"exists": False, "app_id": "storage", "entity_type": entity_type, "entity_id": entity_id}
    record = resolve_file_record(
        data_root=data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
        entity_id=entity_id,
    )
    item = _file_reference(record) if record is not None else None
    if item is None:
        return {"exists": False, "app_id": "storage", "entity_type": "file", "entity_id": entity_id}
    return {"exists": True, **item}


def reference_summarize_payload(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    entity_type = str(body.get("entity_type") or "file").strip() or "file"
    resolved = reference_resolve_payload(
        data_root=data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
        body={"entity_type": entity_type, "entity_id": str(body.get("entity_id") or "")},
    )
    if not resolved.get("exists"):
        return {"summary": "", "safe_fields": {}, "source_updated_at": ""}
    return {
        "summary": resolved.get("summary") or resolved.get("title") or "",
        "safe_fields": {
            "title": resolved.get("title"),
            "path": resolved.get("workspace_relative_path"),
            "kind": entity_type,
        },
        "source_updated_at": "",
    }


def _rank_file_records(records: list[dict[str, Any]], *, query: str) -> list[dict[str, Any]]:
    normalized_query = _normalize_search_text(query)
    if not normalized_query:
        return records
    scored: list[tuple[int, float, str, dict[str, Any]]] = []
    for record in records:
        score = _file_record_score(record, normalized_query)
        if score > 0:
            scored.append((score, _modified_desc_sort_value(record), str(record.get("name") or "").casefold(), record))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [record for _score, _modified, _name, record in scored]


def _rank_folder_records(records: list[dict[str, Any]], *, query: str) -> list[dict[str, Any]]:
    normalized_query = _normalize_search_text(query)
    if not normalized_query:
        return records
    scored: list[tuple[int, float, str, dict[str, Any]]] = []
    for record in records:
        score = _folder_record_score(record, normalized_query)
        if score > 0:
            scored.append((score, _modified_desc_sort_value(record), str(record.get("name") or "").casefold(), record))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [record for _score, _modified, _name, record in scored]


def _file_record_score(record: dict[str, Any], normalized_query: str) -> int:
    texts = [
        _normalize_search_text(record.get("name")),
        _normalize_search_text(record.get("workspace_relative_path")),
        _normalize_search_text(record.get("display_path")),
        _normalize_search_text(record.get("content_type")),
        _normalize_search_text(record.get("preview_kind")),
    ]
    return _reference_match_score(texts, normalized_query, primary_indexes={0, 1, 2})


def _folder_record_score(record: dict[str, Any], normalized_query: str) -> int:
    texts = [
        _normalize_search_text(record.get("name")),
        _normalize_search_text(record.get("workspace_relative_path")),
        _normalize_search_text(record.get("role")),
        "folder storage",
    ]
    return _reference_match_score(texts, normalized_query, primary_indexes={0, 1})


def _reference_match_score(texts: list[str], normalized_query: str, *, primary_indexes: set[int]) -> int:
    if not normalized_query:
        return 0
    score = 0
    for index, text in enumerate(texts):
        if not text:
            continue
        is_primary = index in primary_indexes
        if text == normalized_query:
            score += 2000 if is_primary else 400
        elif text.startswith(normalized_query):
            score += 1200 if is_primary else 220
        elif normalized_query in text:
            score += 800 if is_primary else 160
    tokens = normalized_query.split()
    if not tokens or not all(any(token in text for text in texts) for token in tokens):
        return score
    for token in tokens:
        for index, text in enumerate(texts):
            if token not in text:
                continue
            score += 80 if index in primary_indexes else 20
    return score


def _normalize_search_text(value: object) -> str:
    return re.sub(r"[\s._/\\-]+", " ", str(value if value is not None else "").casefold()).strip()


def _modified_desc_sort_value(record: dict[str, Any]) -> float:
    raw_value = str(record.get("modified_at") or "")
    if not raw_value:
        return 0.0
    try:
        return -datetime.fromisoformat(raw_value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _record_display_path(record: dict[str, Any]) -> str:
    return str(record.get("workspace_relative_path") or record.get("display_path") or "")


def _file_reference(record: dict[str, Any]) -> dict[str, Any]:
    app_page = f"files/{quote(str(record['id']), safe='')}"
    display_path = _record_display_path(record)
    summary = f"{record['preview_kind']} file, {record['size_bytes']} bytes"
    if display_path:
        summary = f"{summary} at {display_path}"
    return {
        "app_id": "storage",
        "entity_type": "file",
        "entity_id": record["id"],
        "title": record["name"],
        "subtitle": display_path,
        "summary": summary,
        "confidence": 1.0,
        "app_page": app_page,
        "deep_link": f"/app/storage/{app_page}",
        "workspace_relative_path": record["workspace_relative_path"],
    }


def _folder_reference(record: dict[str, Any]) -> dict[str, Any]:
    app_page = _folder_app_page(record)
    relative_path = str(record.get("relative_path") or "")
    summary_prefix = "Storage root folder" if not relative_path else "Storage folder"
    summary = f"{summary_prefix} in {record['role']}"
    if record.get("workspace_relative_path"):
        summary = f"{summary} at {record['workspace_relative_path']}"
    return {
        "app_id": "storage",
        "entity_type": "folder",
        "entity_id": _folder_entity_id(record),
        "title": record["name"],
        "subtitle": record["workspace_relative_path"],
        "summary": summary,
        "confidence": 1.0,
        "app_page": app_page,
        "deep_link": f"/app/storage/{app_page}",
        "workspace_relative_path": record["workspace_relative_path"],
        "metadata": {
            "role": record["role"],
            "relative_path": relative_path,
            "workspace_relative_path": record["workspace_relative_path"],
        },
    }


def _folder_entity_id(record: dict[str, Any]) -> str:
    relative_path = quote(str(record.get("relative_path") or ""), safe="/")
    return f"{record['role']}:{relative_path}/" if relative_path else f"{record['role']}:/"


def _folder_app_page(record: dict[str, Any]) -> str:
    role = quote(str(record["role"]), safe="")
    relative_path = quote(str(record.get("relative_path") or ""), safe="/")
    return f"folders/{role}/{relative_path}" if relative_path else f"folders/{role}"


def _storage_root_folder(role: str, root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    stat = root.stat()
    return {
        "id": f"{role}:/",
        "role": role,
        "name": "Uploaded" if role == "uploaded" else "Generated",
        "relative_path": "",
        "workspace_relative_path": f"storage/{role}",
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }


def _folder_records(*, data_root: Path, uploaded_root: Path, generated_root: Path) -> list[dict[str, Any]]:
    catalog = catalog_files_payload(
        data_root=data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
        offset=0,
        limit=1,
    )
    return [
        _storage_root_folder("uploaded", uploaded_root),
        _storage_root_folder("generated", generated_root),
        *catalog["folders"],
    ]


def _folder_matches_query(record: dict[str, Any], query: str) -> bool:
    normalized_query = _normalize_search_text(query)
    if not normalized_query:
        return True
    return _folder_record_score(record, normalized_query) > 0


def _parse_folder_reference(value: str) -> tuple[str, str] | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.startswith("storage/"):
        parts = Path(normalized).parts
        if len(parts) >= 2 and parts[0] == "storage" and parts[1] in STORAGE_FILE_ROLES:
            relative_path = Path(*parts[2:]).as_posix() if len(parts) > 2 else ""
            return parts[1], relative_path
        return None
    role, separator, encoded_relative = normalized.partition(":")
    if not separator or role not in STORAGE_FILE_ROLES:
        return None
    relative_value = unquote(encoded_relative).strip("/")
    if not relative_value:
        return role, ""
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    return role, relative.as_posix()


def _is_hidden_folder(*, role: str, relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return role == "uploaded" and len(parts) == 1 and bool(UPLOAD_BUCKET_PATTERN.fullmatch(parts[0]))


def _resolve_folder_record(
    *,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
    entity_id: str,
) -> dict[str, Any] | None:
    parsed = _parse_folder_reference(entity_id)
    if parsed is None:
        return None
    role, relative_path = parsed
    if relative_path and _is_hidden_folder(role=role, relative_path=relative_path):
        return None
    catalog_files_payload(
        data_root=data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
        offset=0,
        limit=1,
    )
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    folder = (root / relative_path).resolve() if relative_path else root
    if folder != root and root not in folder.parents:
        return None
    if not folder.is_dir():
        return None
    if not relative_path:
        return _storage_root_folder(role, root)
    return next(
        (
            record
            for record in _folder_records(data_root=data_root, uploaded_root=uploaded_root, generated_root=generated_root)
            if record["role"] == role and record["relative_path"] == relative_path
        ),
        None,
    )


def _optional_positive_int(body: dict[str, Any], key: str, *, maximum: int | None = None) -> int | None:
    raw_value = body.get(key)
    if key not in body or raw_value is None or raw_value == "":
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as error:
        raise StorageValidationError(f"{key} must be an integer.") from error
    if value <= 0:
        raise StorageValidationError(f"{key} must be positive.")
    if maximum is not None and value > maximum:
        raise StorageValidationError(f"{key} must be at most {maximum}.")
    return value
