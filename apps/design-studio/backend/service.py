"""Design Studio domain operations shared by backend, CLI, and MCP."""

from __future__ import annotations

from base64 import b64decode
import binascii
import json
from pathlib import Path
import re
import shutil
from time import monotonic
from typing import Any
from uuid import uuid4

from core.app_sdk.app_sidecar import AppSidecarError, app_sidecar
from core.app_sdk.storage import safe_app_data_path

from store import OPENDESIGN_COMMIT, OPENDESIGN_MODE, OPENDESIGN_VERSION, ensure_state, update_state, utc_now


PROJECT_ID_PATTERN = re.compile(r"^design_[a-f0-9]{12}$")
OPENDESIGN_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$")
IMPORT_ID_PATTERN = re.compile(r"^import_[a-f0-9]{12}$")
EXPORT_ID_PATTERN = re.compile(r"^export_[a-f0-9]{12}$")
STORAGE_PATH_PATTERN = re.compile(r"^storage/(uploaded|generated)/(.+)$")
MAX_IMPORT_BYTES = 10 * 1024 * 1024
PROVIDER_MODEL_PROTOCOLS = {"anthropic", "openai", "azure", "google", "ollama", "senseaudio", "aihubmix"}


class DesignStudioError(ValueError):
    """Raised when a Design Studio request is invalid."""

    def __init__(self, error: str, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.error = error
        self.detail = detail
        self.status_code = status_code


def status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return app status and persisted state."""
    state = ensure_state(payload["data_root"])
    app_id = str(payload.get("app_id") or "design-studio")
    return {
        "state": _public_state(state),
        "sidecar": {
            "id": "opendesign",
            "proxy_url": f"/api/apps/{app_id}/sidecars/opendesign/index.html",
            "ready_url": f"/api/apps/{app_id}/sidecars/opendesign/api/ready",
            "version_url": f"/api/apps/{app_id}/sidecars/opendesign/api/version",
        },
        "opendesign": {
            "version": OPENDESIGN_VERSION,
            "commit": OPENDESIGN_COMMIT,
            "mode": OPENDESIGN_MODE,
            "bundle": _opendesign_bundle_summary(),
            "runtime": _opendesign_runtime_status(payload["data_root"]),
        },
    }


def list_projects(payload: dict[str, Any]) -> dict[str, Any]:
    """Return all design projects."""
    return {"projects": _public_state(ensure_state(payload["data_root"]))["projects"]}


def list_opendesign_projects(payload: dict[str, Any]) -> dict[str, Any]:
    """List canonical OpenDesign projects through the invocation broker."""
    response = _opendesign_request(payload, "/api/projects")
    projects = response.get("projects")
    if not isinstance(projects, list) or any(not isinstance(project, dict) for project in projects):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid project list.", status_code=502)
    return {"projects": projects}


def get_project(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Return one design project."""
    raw_project_id = str(arguments.get("project_id") or arguments.get("id") or "").strip()
    if not PROJECT_ID_PATTERN.fullmatch(raw_project_id):
        project_id = _opendesign_project_id(raw_project_id)
        response = _opendesign_request(payload, f"/api/projects/{project_id}")
        project = response.get("project") if isinstance(response.get("project"), dict) else response
        if not isinstance(project, dict) or str(project.get("id") or "") != project_id:
            raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid project.", status_code=502)
        return {"project": project, "od_project_id": project_id}
    project_id = _project_id(raw_project_id)
    project = _find_project(ensure_state(payload["data_root"]), project_id)
    if project is None:
        raise DesignStudioError("project_not_found", f"Design project `{project_id}` was not found.")
    return {"project": project}


def reference_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    """Declare the canonical OpenDesign project reference type."""
    return {
        "app_id": str(payload.get("app_id") or "design-studio"),
        "entity_types": [
            {
                "entity_type": "design_project",
                "display_name": "OpenDesign project",
            }
        ],
    }


def reference_search(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Search OpenDesign projects without reading its private database."""
    query = str(arguments.get("query") or "").strip().casefold()
    limit = arguments.get("limit", 20)
    limit = limit if isinstance(limit, int) and not isinstance(limit, bool) else 20
    projects = list_opendesign_projects(payload)["projects"]
    results = [
        _opendesign_reference_item(payload, project)
        for project in projects
        if not query or query in str(project.get("name") or project.get("id") or "").casefold()
    ]
    return {"results": results[: max(1, min(limit, 100))]}


def reference_resolve(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Resolve one OpenDesign project reference through its governed API."""
    project_id = _opendesign_project_id(arguments.get("entity_id") or arguments.get("project_id"))
    try:
        project = get_project(payload, {"project_id": project_id})["project"]
    except DesignStudioError as error:
        if error.error == "project_not_found":
            return {"entity_type": "design_project", "entity_id": project_id, "exists": False}
        raise
    return {"exists": True, **_opendesign_reference_item(payload, project)}


def reference_summarize(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded summary for one OpenDesign project reference."""
    resolved = reference_resolve(payload, arguments)
    if not resolved.get("exists"):
        return {**resolved, "summary": ""}
    return resolved


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


def handle_sidecar_core_route(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle OpenDesign routes that Maverick intercepts before the sidecar."""
    route_path = _route_path(payload.get("route_path"))
    method = str(payload.get("method") or "GET").upper()
    if _route_matches(route_path, "/api/media/config"):
        return _handle_media_config_route(payload, arguments, method=method)
    if _route_matches(route_path, "/api/projects"):
        return _handle_projects_route(payload, arguments, method=method, route_path=route_path)
    if _route_matches(route_path, "/api/import/storage"):
        return _handle_storage_import_route(payload, arguments, method=method)
    if _route_matches(route_path, "/api/export/storage"):
        return _handle_storage_export_route(payload, arguments, method=method)
    if _route_matches(route_path, "/api/provider"):
        return _handle_provider_proxy_route(payload, arguments, method=method, route_path=route_path)
    raise DesignStudioError(
        "sidecar_core_route_not_found",
        f"Design Studio does not implement handled sidecar route `{route_path}`.",
        status_code=404,
    )


def _handle_media_config_route(payload: dict[str, Any], arguments: dict[str, Any], *, method: str) -> dict[str, Any]:
    if method not in {"GET", "HEAD"}:
        raise DesignStudioError(
            "media_config_managed_by_maverick",
            "Provider media configuration is managed by Maverick and cannot be written through OpenDesign in sandbox mode.",
            status_code=403,
        )
    ensure_state(payload["data_root"])
    provider_proxy = payload.get("provider_proxy") if isinstance(payload.get("provider_proxy"), dict) else {}
    active_provider = provider_proxy.get("active_provider") if isinstance(provider_proxy.get("active_provider"), dict) else None
    providers = [_public_provider_summary(active_provider)] if active_provider else []
    return {
        "status_code": 200,
        "json": {
            "mode": "maverick-proxy",
            "providers": providers,
            "default_provider": providers[0]["provider_id"] if providers else "",
            "credential_source": str(provider_proxy.get("credential_source") or "core-vault"),
            "secrets_persisted": False,
            "sidecar_reached": False,
            "message": "Provider credentials are managed by Maverick/Vault.",
        },
    }


def _handle_projects_route(
    payload: dict[str, Any],
    arguments: dict[str, Any],
    *,
    method: str,
    route_path: str,
) -> dict[str, Any]:
    if route_path not in {"/api/projects", "/api/projects/"}:
        raise DesignStudioError(
            "opendesign_project_route_not_available",
            "This OpenDesign project subroute is not exposed in Maverick sandbox mode.",
            status_code=404,
        )
    if method == "GET":
        return {"status_code": 200, "json": list_projects(payload)}
    if method == "POST":
        return {"status_code": 201, "json": create_project(payload, _sidecar_core_body(arguments))}
    raise DesignStudioError("method_not_allowed", "Project routes require GET or POST.", status_code=405)


def _handle_storage_import_route(payload: dict[str, Any], arguments: dict[str, Any], *, method: str) -> dict[str, Any]:
    if method != "POST":
        raise DesignStudioError("method_not_allowed", "Storage import routes require POST.", status_code=405)
    body = _sidecar_core_body(arguments)
    return import_from_storage(payload, body)


def _handle_storage_export_route(payload: dict[str, Any], arguments: dict[str, Any], *, method: str) -> dict[str, Any]:
    if method != "POST":
        raise DesignStudioError("method_not_allowed", "Storage export routes require POST.", status_code=405)
    body = _sidecar_core_body(arguments)
    return export_to_storage(payload, body)


def _handle_provider_proxy_route(
    payload: dict[str, Any],
    arguments: dict[str, Any],
    *,
    method: str,
    route_path: str,
) -> dict[str, Any]:
    if method != "POST":
        raise DesignStudioError("method_not_allowed", "Provider proxy routes require POST.", status_code=405)
    _assert_provider_key_not_persisted(payload, arguments)
    if route_path not in {"/api/provider/models", "/api/provider/models/"}:
        return _provider_models_error_response(
            "unsupported_protocol",
            "Design Studio sandbox mode supports only OpenDesign provider model discovery.",
            status=404,
        )
    return _handle_provider_models_route(payload, _sidecar_core_body(arguments))


def _handle_provider_models_route(payload: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    started_at = monotonic()
    protocol = str(body.get("protocol") or "").strip().lower()
    if protocol not in PROVIDER_MODEL_PROTOCOLS:
        return {
            "status_code": 400,
            "json": {
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "protocol must be one of anthropic|openai|azure|google|ollama|senseaudio|aihubmix",
                },
                "sidecar_reached": False,
                "secrets_persisted": False,
            },
        }
    if protocol == "azure":
        return _provider_models_error_response(
            "unsupported_protocol",
            "Azure OpenAI deployment discovery is not supported by the Maverick provider proxy.",
            status=200,
            latency_ms=_elapsed_ms(started_at),
        )
    provider_proxy = payload.get("provider_proxy") if isinstance(payload.get("provider_proxy"), dict) else {}
    if not bool(provider_proxy.get("enabled")):
        return _provider_models_error_response(
            "upstream_unavailable",
            "Design Studio is not permitted to use the Maverick provider proxy.",
            status=503,
            latency_ms=_elapsed_ms(started_at),
        )
    if not bool(provider_proxy.get("configured")) or not isinstance(provider_proxy.get("active_provider"), dict):
        detail = str(provider_proxy.get("blocked_detail") or provider_proxy.get("blocked_reason") or "").strip()
        return _provider_models_error_response(
            "upstream_unavailable",
            detail or "Maverick workspace provider is not configured.",
            status=503,
            latency_ms=_elapsed_ms(started_at),
        )
    models = _provider_proxy_models(provider_proxy)
    active_provider = provider_proxy["active_provider"]
    if not models:
        return _provider_models_error_response(
            "no_models",
            "Maverick provider returned no usable text-generation models.",
            status=200,
            latency_ms=_elapsed_ms(started_at),
            provider=active_provider,
        )
    return {
        "status_code": 200,
        "json": {
            "ok": True,
            "kind": "success",
            "latencyMs": _elapsed_ms(started_at),
            "status": 200,
            "models": models,
            "provider": _public_provider_summary(active_provider),
            "mode": "maverick-proxy",
            "credential_source": str(provider_proxy.get("credential_source") or "core-vault"),
            "secrets_persisted": False,
            "sidecar_reached": False,
        },
    }


def _provider_models_error_response(
    kind: str,
    detail: str,
    *,
    status: int,
    latency_ms: int = 0,
    provider: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "kind": kind,
        "latencyMs": latency_ms,
        "status": status,
        "detail": detail[:240],
        "mode": "maverick-proxy",
        "credential_source": "core-vault",
        "secrets_persisted": False,
        "sidecar_reached": False,
    }
    if provider:
        payload["provider"] = _public_provider_summary(provider)
    return {"status_code": 200, "json": payload}


def _provider_proxy_models(provider_proxy: dict[str, Any]) -> list[dict[str, str]]:
    model_settings = provider_proxy.get("model_settings") if isinstance(provider_proxy.get("model_settings"), dict) else {}
    raw_models = model_settings.get("available_models") if isinstance(model_settings, dict) else []
    models: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(raw_models, list):
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id") or item.get("id") or "").strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            models.append({"id": model_id, "label": str(item.get("label") or model_id).strip() or model_id})
    selected_model = str(model_settings.get("selected_model_id") or "").strip() if isinstance(model_settings, dict) else ""
    if selected_model and selected_model not in seen:
        models.append({"id": selected_model, "label": selected_model})
    return sorted(models, key=lambda item: item["id"])


def _public_provider_summary(provider: dict[str, Any]) -> dict[str, str]:
    return {
        "provider_id": str(provider.get("provider_id") or ""),
        "label": str(provider.get("label") or ""),
        "kind": str(provider.get("kind") or ""),
    }


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((monotonic() - started_at) * 1000))


def dispatch(action: str, payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one Design Studio action."""
    if action in {"state", "status"}:
        return status_payload(payload)
    if action == "list_projects":
        return list_projects(payload)
    if action == "list_opendesign_projects":
        return list_opendesign_projects(payload)
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
    if action in {"references.manifest", "reference_manifest"}:
        return reference_manifest(payload)
    if action in {"references.search", "reference_search"}:
        return reference_search(payload, arguments)
    if action in {"references.resolve", "reference_resolve"}:
        return reference_resolve(payload, arguments)
    if action in {"references.summarize", "reference_summarize"}:
        return reference_summarize(payload, arguments)
    if action == "sidecar_core_route":
        return handle_sidecar_core_route(payload, arguments)
    raise DesignStudioError("unsupported_action", f"Unsupported Design Studio action `{action}`.")


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": state.get("schema_version"),
        "projects": state.get("projects", []),
        "view_state": state.get("view_state", {}),
        "route_policy": state.get("route_policy", {}),
        "updated_at": state.get("updated_at", ""),
    }


def _opendesign_bundle_summary() -> dict[str, Any]:
    manifest_path = Path(__file__).resolve().parents[1] / "service" / "opendesign_bundle.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    upstream = payload.get("upstream") if isinstance(payload.get("upstream"), dict) else {}
    distribution = payload.get("distribution") if isinstance(payload.get("distribution"), dict) else {}
    artifact = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else {}
    assets = artifact.get("assets") if isinstance(artifact.get("assets"), dict) else {}
    platform_asset = assets.get("linux-x86_64") if isinstance(assets.get("linux-x86_64"), dict) else {}
    return {
        "repository": upstream.get("repository", ""),
        "tag": upstream.get("tag", ""),
        "commit": upstream.get("commit", ""),
        "distribution": distribution.get("primary", ""),
        "oci_reference": (
            f"{distribution.get('registry', '')}/{distribution.get('repository', '')}:"
            f"{distribution.get('reference', '')}"
        ),
        "oci_index_digest": (
            distribution.get("index", {}).get("digest", "")
            if isinstance(distribution.get("index"), dict)
            else ""
        ),
        "artifact_sha256": platform_asset.get("sha256", ""),
        "default_relative_path": artifact.get("default_relative_path", ""),
    }


def _opendesign_runtime_status(data_root: str) -> dict[str, Any]:
    status_path = Path(data_root) / "opendesign" / "launcher-status.json"
    if status_path.is_symlink() or not status_path.is_file():
        return {"bundle_configured": False, "mode": "not-started", "detail": "", "active": {}}
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"bundle_configured": False, "mode": "not-started", "detail": "", "active": {}}
    active = payload.get("active")
    bundle = payload.get("bundle")
    valid = (
        payload.get("schema_version") == "2"
        and payload.get("opendesign_version") == OPENDESIGN_VERSION
        and payload.get("opendesign_commit") == OPENDESIGN_COMMIT
        and isinstance(active, dict)
        and active.get("od_version") == OPENDESIGN_VERSION
        and isinstance(active.get("bundle_artifact_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", active["bundle_artifact_sha256"]) is not None
        and isinstance(bundle, dict)
        and bundle.get("location") == "verified_registry"
        and bundle.get("relative_path") == active["bundle_artifact_sha256"]
    )
    if not valid:
        return {"bundle_configured": False, "mode": "invalid-status", "detail": "", "active": {}}
    return {
        "bundle_configured": bool(payload.get("bundle_configured")),
        "mode": str(payload.get("mode") or "unknown"),
        "detail": str(payload.get("detail") or ""),
        "active": {
            "bundle_artifact_sha256": active["bundle_artifact_sha256"],
            "od_version": active["od_version"],
            "data_generation": str(active.get("data_generation") or ""),
        },
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


def _opendesign_project_id(value: object) -> str:
    project_id = str(value or "").strip()
    if not OPENDESIGN_PROJECT_ID_PATTERN.fullmatch(project_id) or PROJECT_ID_PATTERN.fullmatch(project_id):
        raise DesignStudioError("invalid_opendesign_project_id", "A valid OpenDesign project id is required.")
    return project_id


def _opendesign_request(payload: dict[str, Any], path: str) -> dict[str, Any]:
    try:
        response = app_sidecar(payload, "opendesign").get(path, headers={"accept": "application/json"})
    except AppSidecarError as error:
        raise DesignStudioError(
            "opendesign_unavailable",
            "OpenDesign is unavailable through the governed app capability.",
            status_code=503,
        ) from error
    if response.status_code == 404:
        raise DesignStudioError("project_not_found", "The OpenDesign project was not found.", status_code=404)
    if response.status_code >= 400:
        raise DesignStudioError(
            "opendesign_request_failed",
            f"OpenDesign returned HTTP {response.status_code}.",
            status_code=502,
        )
    try:
        decoded = response.json()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DesignStudioError(
            "opendesign_response_invalid",
            "OpenDesign returned invalid JSON.",
            status_code=502,
        ) from error
    if not isinstance(decoded, dict):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid response.", status_code=502)
    return decoded


def _opendesign_reference_item(payload: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    project_id = _opendesign_project_id(project.get("id"))
    name = str(project.get("name") or project_id).strip()[:200]
    status = project.get("status")
    status_value = str(status.get("value") or "") if isinstance(status, dict) else str(status or "")
    summary = f"OpenDesign project {name}"
    if status_value:
        summary = f"{summary} ({status_value})"
    app_id = str(payload.get("app_id") or "design-studio")
    return {
        "app_id": app_id,
        "entity_type": "design_project",
        "entity_id": project_id,
        "title": name,
        "summary": summary,
        "app_page": f"projects/{project_id}",
        "deep_link": f"/app/{app_id}/projects/{project_id}",
        "od_project_id": project_id,
    }


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


def _route_path(value: object) -> str:
    path = str(value or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    if "\x00" in path or ".." in Path(path).parts:
        raise DesignStudioError("sidecar_route_invalid", "Invalid handled sidecar route path.", status_code=400)
    return path


def _route_matches(route_path: str, prefix: str) -> bool:
    clean_prefix = prefix.rstrip("/") or "/"
    return route_path == clean_prefix or route_path.startswith(f"{clean_prefix}/")


def _sidecar_core_body(arguments: dict[str, Any]) -> dict[str, Any]:
    body = arguments.get("body") if isinstance(arguments.get("body"), dict) else arguments
    return body if isinstance(body, dict) else {}


def _assert_provider_key_not_persisted(payload: dict[str, Any], arguments: dict[str, Any]) -> None:
    body = _sidecar_core_body(arguments)
    suspicious = _contains_secret_like_value(body)
    media_config_dir = safe_app_data_path(payload["data_root"], Path("opendesign") / "media-config")
    media_config_dir.mkdir(parents=True, exist_ok=True)
    if suspicious:
        marker = media_config_dir / "README.txt"
        if not marker.exists():
            marker.write_text(
                "Provider credentials are intentionally managed by Maverick/Vault and are not persisted here.\n",
                encoding="utf-8",
            )


def _contains_secret_like_value(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"apikey", "api_key", "api-key", "authorization", "token", "secret"} and str(item).strip():
                return True
            if _contains_secret_like_value(item):
                return True
    if isinstance(value, list):
        return any(_contains_secret_like_value(item) for item in value)
    return False


def _should_request_storage_read(payload: dict[str, Any]) -> bool:
    return payload.get("surface") in {"backend", "sidecar_core_handler"} and isinstance(payload.get("app_dependencies"), dict)


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
