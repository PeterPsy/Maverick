"""Design Studio domain operations shared by backend, CLI, and MCP."""

from __future__ import annotations

from base64 import b64decode
import binascii
from pathlib import Path
import re
import shutil
from typing import Any
from uuid import uuid4

from core.app_sdk.storage import safe_app_data_path

from store import OPENDESIGN_COMMIT, OPENDESIGN_VERSION, ensure_state, update_state, utc_now


PROJECT_ID_PATTERN = re.compile(r"^design_[a-f0-9]{12}$")
IMPORT_ID_PATTERN = re.compile(r"^import_[a-f0-9]{12}$")
EXPORT_ID_PATTERN = re.compile(r"^export_[a-f0-9]{12}$")
STORAGE_PATH_PATTERN = re.compile(r"^storage/(uploaded|generated)/(.+)$")
MAX_IMPORT_BYTES = 10 * 1024 * 1024


class DesignStudioError(ValueError):
    """Raised when a Design Studio request is invalid."""

    def __init__(self, error: str, detail: str) -> None:
        super().__init__(detail)
        self.error = error
        self.detail = detail


def status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return app status and persisted state."""
    state = ensure_state(payload["data_root"])
    app_id = str(payload.get("app_id") or "design-studio")
    return {
        "state": _public_state(state),
        "sidecar": {
            "id": "opendesign",
            "proxy_url": f"/api/apps/{app_id}/sidecars/opendesign/",
            "ready_url": f"/api/apps/{app_id}/sidecars/opendesign/api/ready",
            "version_url": f"/api/apps/{app_id}/sidecars/opendesign/api/version",
        },
        "opendesign": {
            "version": OPENDESIGN_VERSION,
            "commit": OPENDESIGN_COMMIT,
            "mode": "governed-sidecar-stub",
        },
    }


def list_projects(payload: dict[str, Any]) -> dict[str, Any]:
    """Return all design projects."""
    return {"projects": _public_state(ensure_state(payload["data_root"]))["projects"]}


def get_project(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Return one design project."""
    project_id = _project_id(arguments.get("project_id") or arguments.get("id"))
    project = _find_project(ensure_state(payload["data_root"]), project_id)
    if project is None:
        raise DesignStudioError("project_not_found", f"Design project `{project_id}` was not found.")
    return {"project": project}


def create_project(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Create one design project in app-owned state."""
    name = _clean_text(arguments.get("name"), fallback="Untitled design")
    prompt = _clean_text(arguments.get("prompt"), fallback="")
    now = utc_now()
    project = {
        "id": f"design_{uuid4().hex[:12]}",
        "name": name,
        "prompt": prompt,
        "status": "draft",
        "source_files": [],
        "imports": [],
        "exports": [],
        "created_at": now,
        "updated_at": now,
    }

    def add(state: dict[str, Any]) -> dict[str, Any]:
        state["projects"].insert(0, project)
        state["view_state"]["selected_project_id"] = project["id"]
        return state

    state = update_state(payload["data_root"], add)
    return {"project": project, "state": _public_state(state)}


def import_from_storage(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Import one bounded Storage file into a design project data directory."""
    data_root = payload["data_root"]
    project_id = _project_id(arguments.get("project_id"))
    workspace_relative_path = _storage_path(arguments.get("workspace_relative_path"))
    if _should_request_storage_read(payload):
        return _request_storage_import(
            data_root=data_root,
            project_id=project_id,
            workspace_relative_path=workspace_relative_path,
        )
    return _import_from_local_storage(
        payload,
        data_root=data_root,
        project_id=project_id,
        workspace_relative_path=workspace_relative_path,
    )


def _request_storage_import(*, data_root: str, project_id: str, workspace_relative_path: str) -> dict[str, Any]:
    import_id = f"import_{uuid4().hex[:12]}"
    requested_at = utc_now()
    import_record = {
        "import_id": import_id,
        "status": "pending",
        "workspace_relative_path": workspace_relative_path,
        "name": Path(workspace_relative_path).name,
        "size_bytes": 0,
        "app_data_path": "",
        "requested_at": requested_at,
        "imported_at": "",
        "error": "",
    }

    def apply_pending_import(state: dict[str, Any]) -> dict[str, Any]:
        project = _require_project(state, project_id)
        project["imports"].append(import_record)
        project["status"] = "importing"
        project["updated_at"] = requested_at
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(data_root, apply_pending_import)
    return {
        "import": import_record,
        "project": _require_project(state, project_id),
        "state": _public_state(state),
        "dependency_backend_requests": [
            _storage_read_request(
                project_id=project_id,
                import_id=import_id,
                workspace_relative_path=workspace_relative_path,
            )
        ],
    }


def _import_from_local_storage(
    payload: dict[str, Any],
    *,
    data_root: str,
    project_id: str,
    workspace_relative_path: str,
) -> dict[str, Any]:
    """Import via mounted local Storage roots for direct CLI/MCP/test entrypoints."""
    source_path = _resolve_storage_file(payload, workspace_relative_path)
    if source_path.stat().st_size > MAX_IMPORT_BYTES:
        raise DesignStudioError("storage_file_too_large", "Design Studio imports are limited to 10 MiB in the sandbox MVP.")
    import_id = f"import_{uuid4().hex[:12]}"
    project_import_dir = safe_app_data_path(data_root, Path("imports") / project_id / import_id)
    project_import_dir.mkdir(parents=True, exist_ok=True)
    target_path = (project_import_dir / source_path.name).resolve()
    shutil.copyfile(source_path, target_path)
    imported = {
        "import_id": import_id,
        "status": "imported",
        "workspace_relative_path": workspace_relative_path,
        "name": source_path.name,
        "size_bytes": source_path.stat().st_size,
        "app_data_path": str(target_path.relative_to(Path(data_root).resolve())),
        "requested_at": utc_now(),
        "imported_at": utc_now(),
        "error": "",
    }

    def apply_import(state: dict[str, Any]) -> dict[str, Any]:
        project = _require_project(state, project_id)
        project["imports"].append(imported)
        _append_source_file(project, workspace_relative_path)
        project["status"] = "imported"
        project["updated_at"] = utc_now()
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(data_root, apply_import)
    return {"import": imported, "project": _require_project(state, project_id), "state": _public_state(state)}


def record_storage_import_result(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Record and materialize the result of one Storage dependency-backend import read."""
    project_id = _project_id(arguments.get("project_id"))
    import_id = _import_id(arguments.get("import_id"))
    workspace_relative_path = _storage_path(arguments.get("workspace_relative_path"))
    dependency_status = str(arguments.get("dependency_backend_status") or "").strip()
    dependency_result = (
        arguments.get("dependency_backend_result")
        if isinstance(arguments.get("dependency_backend_result"), dict)
        else {}
    )
    error = str(arguments.get("error") or "").strip()
    if dependency_status != "completed":
        return _mark_storage_import_failed(
            data_root=payload["data_root"],
            project_id=project_id,
            import_id=import_id,
            error=error or "Storage import read failed.",
        )

    try:
        decoded = _storage_read_result_bytes(dependency_result)
        if len(decoded) > MAX_IMPORT_BYTES:
            return _mark_storage_import_failed(
                data_root=payload["data_root"],
                project_id=project_id,
                import_id=import_id,
                error="Design Studio imports are limited to 10 MiB in the sandbox MVP.",
            )
        file_payload = _storage_read_result_file(dependency_result)
        returned_workspace_path = str(
            file_payload.get("workspace_relative_path") or workspace_relative_path
        ).strip()
        if returned_workspace_path != workspace_relative_path:
            raise DesignStudioError(
                "storage_import_mismatch",
                "Storage read returned a different path than the import requested.",
            )
        file_name = _storage_file_name(workspace_relative_path, file_payload)
    except DesignStudioError as error:
        return _mark_storage_import_failed(
            data_root=payload["data_root"],
            project_id=project_id,
            import_id=import_id,
            error=error.detail,
        )
    project_import_dir = safe_app_data_path(payload["data_root"], Path("imports") / project_id / import_id)
    project_import_dir.mkdir(parents=True, exist_ok=True)
    target_path = (project_import_dir / file_name).resolve()
    if project_import_dir.resolve() != target_path.parent.resolve():
        raise DesignStudioError("storage_import_invalid_name", "Storage returned an invalid file name.")
    target_path.write_bytes(decoded)
    imported_at = utc_now()
    imported = {
        "import_id": import_id,
        "status": "imported",
        "workspace_relative_path": workspace_relative_path,
        "name": file_name,
        "size_bytes": len(decoded),
        "app_data_path": str(target_path.relative_to(Path(payload["data_root"]).resolve())),
        "requested_at": "",
        "imported_at": imported_at,
        "error": "",
    }

    def apply_result(state: dict[str, Any]) -> dict[str, Any]:
        project = _require_project(state, project_id)
        existing = _find_import(project, import_id)
        if existing is None:
            project["imports"].append(imported)
        else:
            imported["requested_at"] = str(existing.get("requested_at") or "")
            existing.update(imported)
        _append_source_file(project, workspace_relative_path)
        project["status"] = "imported"
        project["updated_at"] = imported_at
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(payload["data_root"], apply_result)
    project = _require_project(state, project_id)
    return {"import": _require_import(project, import_id), "project": project, "state": _public_state(state)}


def export_to_storage(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Request governed Storage writes for project metadata and notes."""
    project_id = _project_id(arguments.get("project_id"))
    data_root = payload["data_root"]
    state = ensure_state(data_root)
    project = _require_project(state, project_id)
    export_id = f"export_{uuid4().hex[:12]}"
    exported_at = utc_now()
    manifest = {
        "app_id": "design-studio",
        "opendesign_version": OPENDESIGN_VERSION,
        "opendesign_commit": OPENDESIGN_COMMIT,
        "export_id": export_id,
        "project_id": project_id,
        "project_name": project["name"],
        "source_files": project.get("source_files", []),
        "provider": "maverick-proxy",
        "model": "",
        "created_at": exported_at,
    }
    notes = _export_notes(project, manifest)
    manifest_workspace_path = f"storage/generated/design-studio/{project_id}/{export_id}/manifest.json"
    notes_workspace_path = f"storage/generated/design-studio/{project_id}/{export_id}/notes.md"
    expected_paths = [manifest_workspace_path, notes_workspace_path]
    export_record = {
        "export_id": export_id,
        "status": "pending",
        "workspace_relative_paths": expected_paths,
        "completed_workspace_relative_paths": [],
        "exported_at": exported_at,
        "completed_at": "",
        "error": "",
    }

    def apply_export(next_state: dict[str, Any]) -> dict[str, Any]:
        next_project = _require_project(next_state, project_id)
        next_project["exports"].append(export_record)
        next_project["status"] = "exporting"
        next_project["updated_at"] = exported_at
        next_state["view_state"]["selected_project_id"] = project_id
        return next_state

    next_state = update_state(data_root, apply_export)
    return {
        "export": export_record,
        "project": _require_project(next_state, project_id),
        "state": _public_state(next_state),
        "dependency_backend_requests": [
            _storage_write_request(
                project_id=project_id,
                export_id=export_id,
                workspace_relative_path=manifest_workspace_path,
                content=_json_text(manifest),
                artifact="manifest",
            ),
            _storage_write_request(
                project_id=project_id,
                export_id=export_id,
                workspace_relative_path=notes_workspace_path,
                content=notes,
                artifact="notes",
            ),
        ],
    }


def record_storage_export_result(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Record the result of one Storage dependency-backend export write."""
    project_id = _project_id(arguments.get("project_id"))
    export_id = _export_id(arguments.get("export_id"))
    workspace_relative_path = _storage_path(arguments.get("workspace_relative_path"))
    dependency_status = str(arguments.get("dependency_backend_status") or "").strip()
    dependency_result = arguments.get("dependency_backend_result") if isinstance(arguments.get("dependency_backend_result"), dict) else {}
    error = str(arguments.get("error") or "").strip()
    written_path = _storage_write_result_path(dependency_result) or workspace_relative_path
    if written_path != workspace_relative_path:
        raise DesignStudioError("storage_export_mismatch", "Storage wrote a different path than the export requested.")

    def apply_result(state: dict[str, Any]) -> dict[str, Any]:
        project = _require_project(state, project_id)
        export = _require_export(project, export_id)
        if dependency_status != "completed":
            export["status"] = "failed"
            export["error"] = error or "Storage export write failed."
            project["status"] = "export_failed"
            project["updated_at"] = utc_now()
            return state
        completed = export.setdefault("completed_workspace_relative_paths", [])
        if workspace_relative_path not in completed:
            completed.append(workspace_relative_path)
        expected = set(export.get("workspace_relative_paths", []))
        if expected and expected.issubset(set(completed)) and export.get("status") != "failed":
            export["status"] = "exported"
            export["completed_at"] = utc_now()
            export["error"] = ""
            project["status"] = "exported"
        project["updated_at"] = utc_now()
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(payload["data_root"], apply_result)
    project = _require_project(state, project_id)
    return {"export": _require_export(project, export_id), "project": project, "state": _public_state(state)}


def set_view_filter(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Update the app view filter."""
    query = _clean_text(arguments.get("query"), fallback="")

    def update_view(state: dict[str, Any]) -> dict[str, Any]:
        state["view_state"]["query"] = query
        return state

    return {"state": _public_state(update_state(payload["data_root"], update_view))}


def view_filter(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the current app view state."""
    state = ensure_state(payload["data_root"])
    return {"view_state": state.get("view_state", {})}


def set_custom_view(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Select one curated project when provided by id."""
    project_id = str(arguments.get("project_id") or "").strip()

    def update_view(state: dict[str, Any]) -> dict[str, Any]:
        if project_id:
            _require_project(state, _project_id(project_id))
            state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(payload["data_root"], update_view)
    return {"view_state": state.get("view_state", {}), "state": _public_state(state)}


def clear_custom_view(payload: dict[str, Any]) -> dict[str, Any]:
    """Clear Design Studio filter and curated selection state."""
    def update_view(state: dict[str, Any]) -> dict[str, Any]:
        state["view_state"] = {"query": "", "selected_project_id": ""}
        return state

    state = update_state(payload["data_root"], update_view)
    return {"view_state": state.get("view_state", {}), "state": _public_state(state)}


def dispatch(action: str, payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one Design Studio action."""
    if action in {"state", "status"}:
        return status_payload(payload)
    if action == "list_projects":
        return list_projects(payload)
    if action == "get_project":
        return get_project(payload, arguments)
    if action == "create_project":
        return create_project(payload, arguments)
    if action == "import_from_storage":
        return import_from_storage(payload, arguments)
    if action == "record_storage_import_result":
        return record_storage_import_result(payload, arguments)
    if action == "export_to_storage":
        return export_to_storage(payload, arguments)
    if action == "record_storage_export_result":
        return record_storage_export_result(payload, arguments)
    if action == "set_view_filter":
        return set_view_filter(payload, arguments)
    if action == "view_filter":
        return view_filter(payload)
    if action == "set_custom_view":
        return set_custom_view(payload, arguments)
    if action == "clear_custom_view":
        return clear_custom_view(payload)
    raise DesignStudioError("unsupported_action", f"Unsupported Design Studio action `{action}`.")


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": state.get("schema_version"),
        "projects": state.get("projects", []),
        "view_state": state.get("view_state", {}),
        "route_policy": state.get("route_policy", {}),
        "updated_at": state.get("updated_at", ""),
    }


def _find_project(state: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    for project in state.get("projects", []):
        if project.get("id") == project_id:
            return project
    return None


def _require_project(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    project = _find_project(state, project_id)
    if project is None:
        raise DesignStudioError("project_not_found", f"Design project `{project_id}` was not found.")
    return project


def _find_import(project: dict[str, Any], import_id: str) -> dict[str, Any] | None:
    for item in project.get("imports", []):
        if item.get("import_id") == import_id:
            return item
    return None


def _require_import(project: dict[str, Any], import_id: str) -> dict[str, Any]:
    item = _find_import(project, import_id)
    if item is None:
        raise DesignStudioError("import_not_found", f"Design import `{import_id}` was not found.")
    return item


def _require_export(project: dict[str, Any], export_id: str) -> dict[str, Any]:
    for item in project.get("exports", []):
        if item.get("export_id") == export_id:
            return item
    raise DesignStudioError("export_not_found", f"Design export `{export_id}` was not found.")


def _project_id(value: object) -> str:
    project_id = str(value or "").strip()
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise DesignStudioError("project_id_invalid", "A valid design project id is required.")
    return project_id


def _export_id(value: object) -> str:
    export_id = str(value or "").strip()
    if not EXPORT_ID_PATTERN.fullmatch(export_id):
        raise DesignStudioError("export_id_invalid", "A valid export id is required.")
    return export_id


def _import_id(value: object) -> str:
    import_id = str(value or "").strip()
    if not IMPORT_ID_PATTERN.fullmatch(import_id):
        raise DesignStudioError("import_id_invalid", "A valid import id is required.")
    return import_id


def _storage_path(value: object) -> str:
    path = str(value or "").strip()
    if not STORAGE_PATH_PATTERN.fullmatch(path) or ".." in Path(path).parts:
        raise DesignStudioError("storage_path_invalid", "Use a workspace-relative Storage path under storage/uploaded or storage/generated.")
    return path


def _should_request_storage_read(payload: dict[str, Any]) -> bool:
    return payload.get("surface") == "backend" and isinstance(payload.get("app_dependencies"), dict)


def _append_source_file(project: dict[str, Any], workspace_relative_path: str) -> None:
    source_files = project.setdefault("source_files", [])
    if workspace_relative_path not in source_files:
        source_files.append(workspace_relative_path)


def _mark_storage_import_failed(
    *,
    data_root: str,
    project_id: str,
    import_id: str,
    error: str,
) -> dict[str, Any]:
    failed_at = utc_now()

    def apply_failure(state: dict[str, Any]) -> dict[str, Any]:
        project = _require_project(state, project_id)
        item = _find_import(project, import_id)
        if item is not None:
            item["status"] = "failed"
            item["error"] = error
            item["imported_at"] = ""
        project["status"] = "import_failed"
        project["updated_at"] = failed_at
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(data_root, apply_failure)
    project = _require_project(state, project_id)
    item = _find_import(project, import_id)
    return {"import": item or {}, "project": project, "state": _public_state(state)}


def _resolve_storage_file(payload: dict[str, Any], workspace_relative_path: str) -> Path:
    match = STORAGE_PATH_PATTERN.fullmatch(workspace_relative_path)
    if match is None:
        raise DesignStudioError("storage_path_invalid", "Invalid Storage path.")
    role, relative = match.groups()
    root_key = "uploaded_storage_root" if role == "uploaded" else "generated_storage_root"
    root = Path(str(payload.get(root_key) or "")).resolve()
    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise DesignStudioError("storage_path_invalid", "Storage path escapes its role root.")
    if not path.is_file():
        raise DesignStudioError("storage_file_not_found", f"Storage file `{workspace_relative_path}` was not found.")
    return path


def _storage_read_result_file(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("json") if isinstance(result.get("json"), dict) else result
    file_payload = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    return file_payload


def _storage_read_result_bytes(result: dict[str, Any]) -> bytes:
    payload = result.get("json") if isinstance(result.get("json"), dict) else result
    raw = str(payload.get("content_base64") or "")
    if not raw:
        raise DesignStudioError("storage_import_empty", "Storage did not return file content.")
    try:
        return b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as error:
        raise DesignStudioError(
            "storage_import_invalid_content",
            "Storage returned invalid base64 content.",
        ) from error


def _storage_file_name(workspace_relative_path: str, file_payload: dict[str, Any]) -> str:
    name = str(file_payload.get("name") or Path(workspace_relative_path).name).strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise DesignStudioError("storage_import_invalid_name", "Storage returned an invalid file name.")
    return name


def _clean_text(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    return text[:500] if text else fallback


def _export_notes(project: dict[str, Any], manifest: dict[str, Any]) -> str:
    source_files = project.get("source_files", [])
    source_lines = "\n".join(f"- `{item}`" for item in source_files) if source_files else "- None"
    return (
        f"# {project['name']}\n\n"
        f"Project id: `{project['id']}`\n\n"
        f"Export id: `{manifest['export_id']}`\n\n"
        f"Status: `{project.get('status', 'draft')}`\n\n"
        f"OpenDesign: `{manifest['opendesign_version']}` "
        f"({manifest['opendesign_commit']})\n\n"
        f"## Prompt\n\n{project.get('prompt') or 'No prompt recorded.'}\n\n"
        f"## Source Files\n\n{source_lines}\n"
    )


def _storage_write_request(
    *,
    project_id: str,
    export_id: str,
    workspace_relative_path: str,
    content: str,
    artifact: str,
) -> dict[str, Any]:
    return {
        "request_id": f"{export_id}-{artifact}",
        "dependency_alias": "storage-write",
        "body": {
            "action": "file.content.write",
            "workspace_relative_path": workspace_relative_path,
            "mode": "create",
            "content": content,
        },
        "callback": {
            "action": "record_storage_export_result",
            "payload": {
                "project_id": project_id,
                "export_id": export_id,
                "workspace_relative_path": workspace_relative_path,
                "artifact": artifact,
            },
        },
    }


def _storage_read_request(
    *,
    project_id: str,
    import_id: str,
    workspace_relative_path: str,
) -> dict[str, Any]:
    return {
        "request_id": import_id,
        "dependency_alias": "storage-read",
        "body": {
            "action": "file.content.read",
            "workspace_relative_path": workspace_relative_path,
            "max_bytes": MAX_IMPORT_BYTES,
        },
        "callback": {
            "action": "record_storage_import_result",
            "payload": {
                "project_id": project_id,
                "import_id": import_id,
                "workspace_relative_path": workspace_relative_path,
            },
        },
    }


def _storage_write_result_path(result: dict[str, Any]) -> str:
    payload = result.get("json") if isinstance(result.get("json"), dict) else result
    file_payload = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    return str(file_payload.get("workspace_relative_path") or "").strip()


def _json_text(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
