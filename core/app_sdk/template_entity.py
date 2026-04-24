"""SQLite entity app template inspired by the CRM app shape."""

from __future__ import annotations

from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.template_common import normalize_entities, snake_from_slug, title_from_slug
from core.app_sdk.template_react import react_vite_files


def entity_sqlite_files(request: AppSdkCreateRequest) -> dict[str, str]:
    """Render files for a SQLite-backed entity app."""
    entities = normalize_entities(request.entities)
    app_module = snake_from_slug(request.app_id)
    files = {
        "backend/__init__.py": "",
        "backend/database.py": _database_module(request, entities),
        "backend/store.py": _store_module(entities),
        "backend/service.py": _entity_service(request, entities),
        "backend/app_backend.py": _backend_entrypoint(),
        "cli/app_cli.py": _cli_entrypoint(),
        "mcp/server.py": _mcp_entrypoint(request, entities),
        "hooks/install.py": _hook("install"),
        "hooks/migrate.py": _hook("migrate"),
        "hooks/health_check.py": _health_hook(),
        f"skills/{request.app_id}-ops/SKILL.md": _skill(request, entities),
        "tests/test_entrypoints.py": _entrypoint_test(request, entities),
    }
    files.update(react_vite_files(request))
    files["frontend/src/main.tsx"] = _entity_frontend(request, entities)
    title = request.name or title_from_slug(request.app_id)
    files["frontend/dist/index.html"] = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body><main><h1>{title}</h1><p>Entity app ready. Rebuild frontend for full React UI.</p></main></body></html>
"""
    files["backend/app_id.py"] = f'APP_ID = "{request.app_id}"\nAPP_MODULE = "{app_module}"\n'
    return files


def _database_module(request: AppSdkCreateRequest, entities: list[str]) -> str:
    table_sql = "\n".join(
        f"""            CREATE TABLE IF NOT EXISTS {entity}s (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              summary TEXT NOT NULL DEFAULT '',
              metadata_json TEXT NOT NULL DEFAULT '{{}}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_{entity}s_updated ON {entity}s(updated_at);
"""
        for entity in entities
    )
    return f'''"""SQLite database helpers for `{request.app_id}`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3


SCHEMA_VERSION = "1"
ENTITIES = {entities!r}


def now_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat()


def db_path(data_root: Path) -> Path:
    return data_root / "app.sqlite"


def connect(data_root: Path) -> sqlite3.Connection:
    data_root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path(data_root))
    connection.row_factory = sqlite3.Row
    return connection


def ensure_schema(data_root: Path) -> None:
    with connect(data_root) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
{table_sql}        """)
        db.execute(
            "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
            ("schema_version", SCHEMA_VERSION),
        )


def health_payload(data_root: Path) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        version = db.execute("SELECT value FROM schema_metadata WHERE key = 'schema_version'").fetchone()
    return {{"schema_version": version["value"] if version else SCHEMA_VERSION, "database": str(db_path(data_root))}}
'''


def _store_module(entities: list[str]) -> str:
    return f'''"""SQLite store for generated entity records."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from database import ENTITIES, connect, ensure_schema, now_timestamp


def list_records(data_root: Path, entity_type: str) -> list[dict[str, object]]:
    entity = _entity(entity_type)
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute(
            f"SELECT * FROM {{entity}}s WHERE deleted_at IS NULL ORDER BY updated_at DESC"
        ).fetchall()
    return [_row(row) for row in rows]


def create_record(data_root: Path, entity_type: str, title: str, summary: str = "") -> dict[str, object]:
    entity = _entity(entity_type)
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("title is required")
    now = now_timestamp()
    record_id = f"{{entity}}_{{uuid4().hex[:16]}}"
    ensure_schema(data_root)
    with connect(data_root) as db:
        db.execute(
            f"INSERT INTO {{entity}}s(id, title, summary, metadata_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record_id, clean_title, summary.strip(), "{{}}", now, now),
        )
    return get_record(data_root, entity, record_id)


def get_record(data_root: Path, entity_type: str, record_id: str) -> dict[str, object]:
    entity = _entity(entity_type)
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute(f"SELECT * FROM {{entity}}s WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
    if row is None:
        raise ValueError(f"{{entity}} `{{record_id}}` was not found")
    return _row(row)


def search_records(data_root: Path, query: str) -> list[dict[str, object]]:
    needle = f"%{{query.strip()}}%"
    ensure_schema(data_root)
    results: list[dict[str, object]] = []
    with connect(data_root) as db:
        for entity in ENTITIES:
            rows = db.execute(
                f"SELECT * FROM {{entity}}s WHERE deleted_at IS NULL AND (title LIKE ? OR summary LIKE ?) ORDER BY updated_at DESC",
                (needle, needle),
            ).fetchall()
            results.extend(_row(row) for row in rows)
    return results


def reference_manifest() -> dict[str, object]:
    return {{"entity_types": [{{"entity_type": entity, "display_name": entity.replace("_", " ").title()}} for entity in ENTITIES]}}


def reference_summary(data_root: Path, entity_type: str, record_id: str) -> dict[str, object]:
    item = get_record(data_root, entity_type, record_id)
    return {{
        "entity_type": item["entity_type"],
        "entity_id": item["id"],
        "title": item["title"],
        "summary": item["summary"],
        "updated_at": item["updated_at"],
    }}


def load_view_state(data_root: Path) -> dict[str, object]:
    path = data_root / "view_state.json"
    if not path.exists():
        return {{"schema_version": "1", "view_filter": _default_view_filter()}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {{}}
    if not isinstance(raw, dict):
        raw = {{}}
    view_filter = raw.get("view_filter")
    if not isinstance(view_filter, dict):
        view_filter = _default_view_filter()
    return {{"schema_version": "1", "view_filter": view_filter}}


def set_view_filter(
    data_root: Path,
    *,
    query: object = None,
    entity_type: object = None,
    preserve_custom: bool = False,
) -> dict[str, object]:
    current = load_view_state(data_root)
    current_filter = current.get("view_filter") if isinstance(current.get("view_filter"), dict) else {{}}
    if preserve_custom and current_filter.get("mode") == "custom":
        next_filter = dict(current_filter)
        next_filter["query"] = str(query or next_filter.get("query") or "").strip()
        next_filter["entity_type"] = str(entity_type or next_filter.get("entity_type") or ENTITIES[0]).strip()
    else:
        next_filter = _default_view_filter()
        next_filter["query"] = str(query or "").strip()
        next_filter["entity_type"] = str(entity_type or ENTITIES[0]).strip()
    next_filter["updated_at"] = now_timestamp()
    return _write_view_state(data_root, next_filter)


def set_custom_view(data_root: Path, *, title: object = None, refs: object = None) -> dict[str, object]:
    view_filter = {{
        "mode": "custom",
        "query": "",
        "entity_type": ENTITIES[0],
        "title": str(title or "Custom view").strip() or "Custom view",
        "refs": refs if isinstance(refs, list) else [],
        "updated_at": now_timestamp(),
    }}
    return _write_view_state(data_root, view_filter)


def clear_custom_view(data_root: Path) -> dict[str, object]:
    view_filter = _default_view_filter()
    view_filter["updated_at"] = now_timestamp()
    return _write_view_state(data_root, view_filter)


def _entity(entity_type: str) -> str:
    entity = str(entity_type or "{entities[0]}").strip()
    if entity not in ENTITIES:
        raise ValueError(f"Unsupported entity_type `{{entity}}`")
    return entity


def _row(row) -> dict[str, object]:
    payload = dict(row)
    payload["entity_type"] = next(entity for entity in ENTITIES if payload["id"].startswith(f"{{entity}}_"))
    payload["metadata"] = json.loads(payload.pop("metadata_json") or "{{}}")
    return payload


def _default_view_filter() -> dict[str, object]:
    return {{
        "mode": "search",
        "query": "",
        "entity_type": ENTITIES[0],
        "refs": [],
        "updated_at": None,
    }}


def _write_view_state(data_root: Path, view_filter: dict[str, object]) -> dict[str, object]:
    data_root.mkdir(parents=True, exist_ok=True)
    state = {{"schema_version": "1", "view_filter": view_filter}}
    (data_root / "view_state.json").write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\\n", encoding="utf-8")
    return state
'''


def _entity_service(request: AppSdkCreateRequest, entities: list[str]) -> str:
    return f'''"""Service layer for `{request.app_id}`."""

from __future__ import annotations

from pathlib import Path

from database import health_payload
from store import (
    clear_custom_view,
    create_record,
    get_record,
    list_records,
    load_view_state,
    reference_manifest,
    reference_summary,
    search_records,
    set_custom_view,
    set_view_filter,
)


MUTATING_ACTIONS = {{"create", "clear_custom_view", "set_custom_view", "set_view_filter"}}


def handle_action(data_root: Path, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    action = str(payload.get("action") or "list")
    try:
        if action == "status":
            return 200, {{"app_id": "{request.app_id}", "status": "ready", **health_payload(data_root)}}
        if action == "reference_manifest":
            return 200, reference_manifest()
        if action == "reference_search":
            return 200, {{"items": search_records(data_root, str(payload.get("query") or ""))}}
        if action == "reference_resolve":
            return 200, {{
                "item": get_record(
                    data_root,
                    str(payload.get("entity_type") or "{entities[0]}"),
                    str(payload.get("id") or payload.get("entity_id") or ""),
                )
            }}
        if action == "reference_summarize":
            return 200, {{
                "summary": reference_summary(
                    data_root,
                    str(payload.get("entity_type") or "{entities[0]}"),
                    str(payload.get("id") or payload.get("entity_id") or ""),
                )
            }}
        if action == "view_filter":
            return 200, {{"state": load_view_state(data_root)}}
        if action == "set_view_filter":
            return 200, {{
                "state": set_view_filter(
                    data_root,
                    query=payload.get("query"),
                    entity_type=payload.get("entity_type"),
                    preserve_custom=bool(payload.get("preserve_custom")),
                )
            }}
        if action == "set_custom_view":
            return 200, {{"state": set_custom_view(data_root, title=payload.get("title"), refs=payload.get("refs"))}}
        if action == "clear_custom_view":
            return 200, {{"state": clear_custom_view(data_root)}}
        if action == "list":
            return 200, {{"items": list_records(data_root, str(payload.get("entity_type") or "{entities[0]}"))}}
        if action == "create":
            item = create_record(
                data_root,
                str(payload.get("entity_type") or "{entities[0]}"),
                str(payload.get("title") or ""),
                str(payload.get("summary") or ""),
            )
            return 201, {{"item": item}}
        if action == "get":
            return 200, {{
                "item": get_record(
                    data_root,
                    str(payload.get("entity_type") or "{entities[0]}"),
                    str(payload.get("id") or ""),
                )
            }}
        if action == "search":
            return 200, {{"items": search_records(data_root, str(payload.get("query") or ""))}}
    except ValueError as error:
        return 400, {{"error": "validation_error", "detail": str(error)}}
    return 400, {{"error": "unsupported_action", "detail": f"Unsupported action `{{action}}`."}}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action not in MUTATING_ACTIONS:
        return []
    resource = "view-state" if action in {{"clear_custom_view", "set_custom_view", "set_view_filter"}} else "records"
    return [{{"type": "maverick.app.data-changed", "owner_app_id": "{request.app_id}", "resource": resource}}]
'''


def _backend_entrypoint() -> str:
    return '''"""Mounted backend entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
action = str(payload.body.get("action") or "list")
status_code, result = handle_action(Path(payload.data_root), payload.body)
response = backend_response(status_code, result)
if status_code < 400:
    response["app_events"] = app_events_for_action(action)
emit_json(response)
'''


def _cli_entrypoint() -> str:
    return '''"""CLI entrypoint for this entity app."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
arguments.setdefault("action", "list")
status_code, result = handle_action(Path(payload.data_root), arguments)
result["status_code"] = status_code
if status_code < 400:
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "list"))
emit_json(result)
'''


def _mcp_entrypoint(request: AppSdkCreateRequest, entities: list[str]) -> str:
    tool_prefix = request.app_id.replace("-", "_")
    mapping = {
        f"{tool_prefix}_reference_manifest": "reference_manifest",
        f"{tool_prefix}_reference_search": "reference_search",
        f"{tool_prefix}_reference_resolve": "reference_resolve",
        f"{tool_prefix}_reference_summarize": "reference_summarize",
        f"{tool_prefix}_view_filter": "view_filter",
        f"{tool_prefix}_set_view_filter": "set_view_filter",
        f"{tool_prefix}_set_custom_view": "set_custom_view",
        f"{tool_prefix}_clear_custom_view": "clear_custom_view",
        f"{tool_prefix}_list": "list",
        f"{tool_prefix}_create": "create",
        f"{tool_prefix}_get": "get",
        f"{tool_prefix}_search": "search",
    }
    return f'''"""MCP entrypoint for `{request.app_id}`."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action


TOOL_ACTIONS = {mapping!r}


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
tool_name = str(payload.raw.get("tool_name") or "")
arguments.setdefault("action", TOOL_ACTIONS.get(tool_name, "list"))
status_code, result = handle_action(Path(payload.data_root), arguments)
if status_code < 400:
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "list"))
emit_json(result)
'''


def _hook(name: str) -> str:
    return f'''"""Idempotent {name} hook for this entity app."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import ensure_schema, health_payload


payload = json.loads(sys.stdin.read() or "{{}}")
data_root = Path(payload["data_root"])
ensure_schema(data_root)
print(json.dumps({{"ok": True, **health_payload(data_root)}}, ensure_ascii=True))
'''


def _health_hook() -> str:
    return _hook("health_check")


def _skill(request: AppSdkCreateRequest, entities: list[str]) -> str:
    return f"""---
name: {request.app_id}-ops
description: Use the `{request.app_id}` app through its CLI and MCP surfaces.
---

# {request.name or title_from_slug(request.app_id)} Operations

Use official CLI or MCP surfaces to list, create, get, search, and inspect references for: {", ".join(entities)}.
"""


def _entrypoint_test(request: AppSdkCreateRequest, entities: list[str]) -> str:
    return f'''"""Generated entrypoint tests for `{request.app_id}`."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from backend.service import handle_action


class GeneratedEntityEntrypointTest(unittest.TestCase):
    def test_create_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            status, created = handle_action(data_root, {{"action": "create", "entity_type": "{entities[0]}", "title": "Example"}})
            self.assertEqual(status, 201)
            status, listed = handle_action(data_root, {{"action": "list", "entity_type": "{entities[0]}"}})
            self.assertEqual(status, 200)
            self.assertEqual(len(listed["items"]), 1)
            self.assertEqual(created["item"]["title"], "Example")


if __name__ == "__main__":
    unittest.main()
'''


def _entity_frontend(request: AppSdkCreateRequest, entities: list[str]) -> str:
    title = request.name or title_from_slug(request.app_id)
    default_entity = entities[0]
    return f"""import React, {{ useEffect, useState }} from 'react';
import {{ createRoot }} from 'react-dom/client';
import './styles.css';

type Item = {{ id: string; title: string; summary?: string }};

async function callBackend(body: Record<string, unknown>) {{
  const response = await fetch('/api/apps/{request.app_id}/backend', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body)
  }});
  return response.json();
}}

function App() {{
  const [items, setItems] = useState<Item[]>([]);
  const [titleValue, setTitleValue] = useState('');
  const load = async () => {{
    const result = await callBackend({{ action: 'list', entity_type: '{default_entity}' }});
    setItems(result.items || []);
  }};
  useEffect(() => {{ load(); }}, []);
  return (
    <main>
      <h1>{title}</h1>
      <form onSubmit={{async (event) => {{
        event.preventDefault();
        await callBackend({{ action: 'create', entity_type: '{default_entity}', title: titleValue }});
        setTitleValue('');
        await load();
      }}}}>
        <input value={{titleValue}} onChange={{(event) => setTitleValue(event.target.value)}} placeholder="New {default_entity.replace("_", " ")}" />
        <button>Create</button>
      </form>
      <section>
        {{items.map((item) => <article key={{item.id}}><strong>{{item.title}}</strong><small>{{item.id}}</small></article>)}}
      </section>
    </main>
  );
}}

createRoot(document.getElementById('root')!).render(<App />);
"""
