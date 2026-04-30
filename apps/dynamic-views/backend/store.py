"""Workspace-owned persistence for Dynamic Views."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from uuid import uuid4

from errors import DynamicViewsValidationError
from security import validate_dynamic_view_package_source
from core.app_sdk.storage import read_json_state, update_json_state, write_json_state


SCHEMA_VERSION = "1"
DYNAMIC_VIEW_KIND = "dynamic.view.instance"
FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def state_path(data_root: Path) -> Path:
    return data_root / "state.json"


def assets_root(data_root: Path) -> Path:
    return data_root / "assets"


def seed_state(data_root: Path) -> dict:
    data_root.mkdir(parents=True, exist_ok=True)
    assets_root(data_root).mkdir(parents=True, exist_ok=True)
    path = state_path(data_root)
    if not path.exists():
        payload = {"schema_version": SCHEMA_VERSION, "packages": [], "instances": []}
        write_json_state(data_root, "state.json", payload)
    return load_state(data_root)


def load_state(data_root: Path) -> dict:
    data_root.mkdir(parents=True, exist_ok=True)
    path = state_path(data_root)
    if not path.exists():
        return seed_state(data_root)
    payload = read_json_state(data_root, "state.json")
    if not isinstance(payload, dict):
        raise DynamicViewsValidationError("Dynamic Views state must be a JSON object.")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("packages", [])
    payload.setdefault("instances", [])
    if not isinstance(payload["packages"], list) or not isinstance(payload["instances"], list):
        raise DynamicViewsValidationError("Dynamic Views state collections must be arrays.")
    return payload


def save_state(data_root: Path, state: dict) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    write_json_state(data_root, "state.json", state)


def mutate_state(data_root: Path, mutator) -> tuple[dict, dict]:
    result: dict = {}

    def _update(payload: dict) -> dict:
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload.setdefault("packages", [])
        payload.setdefault("instances", [])
        if not isinstance(payload["packages"], list) or not isinstance(payload["instances"], list):
            raise DynamicViewsValidationError("Dynamic Views state collections must be arrays.")
        result.update(mutator(payload) or {})
        return payload

    state = update_json_state(
        data_root,
        "state.json",
        _update,
        default={"schema_version": SCHEMA_VERSION, "packages": [], "instances": []},
    )
    return state, result


def _sanitize_segment(value: str) -> str:
    cleaned = FILENAME_SANITIZER.sub("-", str(value or "").strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-.")
    return cleaned or "item"


def _expect_text(payload: dict, key: str, *, required: bool = False) -> str:
    value = str(payload.get(key) or "").strip()
    if required and not value:
        raise DynamicViewsValidationError(f"{key} is required.")
    return value


def _normalize_binding(raw: dict) -> dict:
    source_type = str(raw.get("sourceType") or raw.get("source_type") or "").strip()
    source_ref = str(raw.get("sourceRef") or raw.get("source_ref") or "").strip()
    if not source_type or not source_ref:
        raise DynamicViewsValidationError("Each data binding requires sourceType and sourceRef.")
    return {
        "source_type": source_type,
        "source_ref": source_ref,
        "query": raw.get("query"),
        "snapshot": raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else None,
    }


def _find_by_id(items: list[dict], item_id: str) -> dict | None:
    for item in items:
        if item.get("id") == item_id:
            return item
    return None


def _write_package_assets(data_root: Path, package: dict) -> tuple[str, str]:
    package_dir = assets_root(data_root) / _sanitize_segment(package["id"])
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = package_dir / "package.json"
    preview = package_dir / "package.html"
    manifest_payload = {
        "id": package["id"],
        "title": package["title"],
        "summary": package.get("summary") or "",
        "renderer": package["renderer"],
        "html": package["html"],
        "css": package.get("css") or "",
        "javascript": package.get("javascript") or "",
        "tags": list(package.get("tags") or []),
        "data_schema": dict(package.get("data_schema") or {}),
        "security_report": dict(package.get("security_report") or {}),
    }
    manifest.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    preview.write_text(build_srcdoc(package=package, data={}, metadata={"packageId": package["id"]}), encoding="utf-8")
    return str(manifest.relative_to(data_root)), str(preview.relative_to(data_root))


def build_srcdoc(*, package: dict, data: dict, metadata: dict) -> str:
    payload = json.dumps({"data": data, "metadata": metadata}, ensure_ascii=True)
    return (
        "<!doctype html><html><head><meta charset='utf-8' />"
        "<meta name='viewport' content='width=device-width, initial-scale=1' />"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'\" />"
        f"<style>{package.get('css') or ''}</style></head><body>"
        f"{package.get('html') or ''}"
        "<script>"
        f"window.MaverickDynamicView = {payload};"
        "window.addEventListener('error', function(event) {"
        "document.body.setAttribute('data-maverick-error', String(event.message || 'runtime-error'));"
        "});"
        "</script>"
        f"<script>{package.get('javascript') or ''}</script>"
        "</body></html>"
    )


def normalize_instance(instance: dict, package: dict) -> dict:
    return {
        "id": instance["id"],
        "workspace_id": instance["workspace_id"],
        "owner_user_id": instance["owner_user_id"],
        "source_instance_id": instance.get("source_instance_id"),
        "package_id": instance["package_id"],
        "title": instance["title"],
        "summary": instance.get("summary") or "",
        "package": package,
        "data": dict(instance.get("data") or {}),
        "data_bindings": list(instance.get("data_bindings") or []),
        "snapshot_mode": instance.get("snapshot_mode") or "snapshot",
        "status": instance.get("status") or "ready",
        "created_at": instance["created_at"],
        "updated_at": instance["updated_at"],
    }


def chat_render(instance: dict) -> dict:
    package = instance["package"]
    return {
        "kind": DYNAMIC_VIEW_KIND,
        "memory": {"instance_id": instance["id"], "package_id": instance["package_id"]},
        "payload": {
            "id": instance["id"],
            "instanceId": instance["id"],
            "title": instance["title"],
            "summary": instance.get("summary") or "",
            "snapshotMode": instance.get("snapshot_mode") or "snapshot",
            "package": {
                "id": package["id"],
                "title": package["title"],
                "summary": package.get("summary") or "",
                "renderer": package.get("renderer") or "sandbox_html_v1",
                "html": package.get("html") or "",
                "css": package.get("css") or "",
                "javascript": package.get("javascript") or "",
                "securityReport": package.get("security_report") or {"status": "approved", "checks": []},
                "tags": list(package.get("tags") or []),
            },
            "data": dict(instance.get("data") or {}),
            "dataBindings": list(instance.get("data_bindings") or []),
            "createdAt": instance["created_at"],
            "updatedAt": instance["updated_at"],
        },
    }


def create_instance(data_root: Path, *, workspace_id: str, owner_user_id: str, source_instance_id: str | None, payload: dict) -> dict:
    create_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    package_input = create_payload.get("package") if isinstance(create_payload.get("package"), dict) else {}
    title = _expect_text(create_payload, "title", required=True)
    summary = _expect_text(create_payload, "summary")
    html = _expect_text(package_input, "html", required=True)
    css = str(package_input.get("css") or "")
    javascript = str(package_input.get("javascript") or "")
    renderer = str(package_input.get("renderer") or "sandbox_html_v1").strip()
    if renderer != "sandbox_html_v1":
        raise DynamicViewsValidationError("Only sandbox_html_v1 renderer is supported.")
    security_report = validate_dynamic_view_package_source(html=html, css=css, javascript=javascript)
    timestamp = _now()
    package = {
        "id": _new_id("pkg"),
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "source_instance_id": source_instance_id,
        "title": title,
        "summary": summary,
        "renderer": renderer,
        "html": html,
        "css": css,
        "javascript": javascript,
        "data_schema": dict(package_input.get("dataSchema") or package_input.get("data_schema") or {}),
        "security_report": security_report,
        "tags": [str(tag).strip() for tag in list(package_input.get("tags") or []) if str(tag).strip()],
        "status": "ready",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    manifest_path, html_path = _write_package_assets(data_root, package)
    package["asset_manifest_path"] = manifest_path
    package["asset_html_path"] = html_path
    bindings = [_normalize_binding(item) for item in list(create_payload.get("dataBindings") or create_payload.get("data_bindings") or [])]
    instance = {
        "id": _new_id("view"),
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "source_instance_id": source_instance_id,
        "package_id": package["id"],
        "title": title,
        "summary": summary,
        "data": dict(create_payload.get("data") or {}),
        "data_bindings": bindings,
        "snapshot_mode": str(create_payload.get("snapshotMode") or create_payload.get("snapshot_mode") or "snapshot"),
        "status": "ready",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if instance["snapshot_mode"] not in {"snapshot", "live"}:
        raise DynamicViewsValidationError("snapshotMode must be snapshot or live.")
    def _append_created(state: dict) -> dict:
        state["packages"].append(package)
        state["instances"].append(instance)
        return {}

    mutate_state(data_root, _append_created)
    hydrated = normalize_instance(instance, package)
    return {
        "action": "create",
        "summary": f"dynamic view create | id={hydrated['id']} | title={hydrated['title']}",
        "package": package,
        "instance": hydrated,
        "chat_render": chat_render(hydrated),
    }
