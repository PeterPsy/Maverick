"""Design Studio domain operations shared by backend, CLI, and MCP."""

from __future__ import annotations

from base64 import b64decode, b64encode
import binascii
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from math import isfinite
import mimetypes
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
from time import monotonic, time
from typing import Any
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from core.app_sdk.app_sidecar import AppSidecarError, app_sidecar
from core.app_sdk.storage import safe_app_data_path

from store import OPENDESIGN_COMMIT, OPENDESIGN_MODE, OPENDESIGN_VERSION, ensure_state, update_state, utc_now
from runtime_bridge import (
    RuntimeBridgeError,
    binding_store_for_payload,
    build_result_package,
    cleanup_binding_store_for_payload,
    cleanup_store_for_payload,
    mark_cancel_requested,
    project_root_relative_to_app_data,
    public_run,
    record_submission,
    record_terminal,
    reserve_run,
    store_for_payload,
    trusted_sidecar_runtime_metadata_payload,
    translate_stream_events,
    validated_identifier,
)


PROJECT_ID_PATTERN = re.compile(r"^design_[a-f0-9]{12}$")
OPENDESIGN_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$")
IMPORT_ID_PATTERN = re.compile(r"^import_[a-f0-9]{12}$")
EXPORT_ID_PATTERN = re.compile(r"^export_[a-f0-9]{12}$")
STORAGE_PATH_PATTERN = re.compile(r"^storage/(uploaded|generated)/(.+)$")
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_EXPORT_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_LEGACY_MAP_BYTES = 2 * 1024 * 1024
MAX_JOB_RECORDS = 1000
PROVIDER_MODEL_PROTOCOLS = {"anthropic", "openai", "azure", "google", "ollama", "senseaudio", "aihubmix"}
APP_CONFIG_SCALAR_KEYS = {"skillId", "designSystemId"}
APP_CONFIG_LIST_KEYS = {"disabledSkills", "disabledDesignSystems"}
APP_CONFIG_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


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
    """Return the canonical OpenDesign project catalog."""
    return list_opendesign_projects(payload)


def list_opendesign_projects(payload: dict[str, Any]) -> dict[str, Any]:
    """List canonical OpenDesign projects through the invocation broker."""
    response = _opendesign_request(payload, "/api/projects")
    projects = response.get("projects")
    if not isinstance(projects, list) or any(not isinstance(project, dict) for project in projects):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid project list.", status_code=502)
    return {"projects": projects}


def resolve_launch_target(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Resolve the hosted launch without ever falling back to OpenDesign Home."""
    projects = list_opendesign_projects(payload)["projects"]
    requested_id = str(arguments.get("od_project_id") or arguments.get("project_id") or "").strip()
    if requested_id:
        try:
            requested_id = validated_identifier(requested_id, label="OpenDesign project id")
        except RuntimeBridgeError as error:
            raise DesignStudioError("project_id_invalid", str(error)) from error
        selected = next((project for project in projects if str(project.get("id") or "") == requested_id), None)
        if selected is None:
            raise DesignStudioError("project_not_found", "The OpenDesign project was not found.", status_code=404)
        return {"target": "project", "od_project_id": requested_id, "project": selected}
    if not projects:
        return {"target": "empty", "od_project_id": "", "project": None}
    selected = max(
        projects,
        key=lambda project: (_project_created_at(project), str(project.get("id") or "")),
    )
    try:
        selected_id = validated_identifier(selected.get("id"), label="OpenDesign project id")
    except RuntimeBridgeError as error:
        raise DesignStudioError(
            "opendesign_response_invalid",
            "OpenDesign returned a project without a valid identifier.",
            status_code=502,
        ) from error
    return {"target": "project", "od_project_id": selected_id, "project": selected}


def _project_created_at(project: dict[str, Any]) -> float:
    value = project.get("createdAt", project.get("created_at"))
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not isfinite(numeric):
            return 0.0
        return numeric * 1000 if abs(numeric) < 100_000_000_000 else numeric
    if not isinstance(value, str) or not value.strip():
        return 0.0
    text = value.strip()
    try:
        return _project_created_at({"createdAt": float(text)})
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp() * 1000


def get_project(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Return one canonical OpenDesign project, resolving a legacy alias once."""
    identity = _resolve_project_identity(
        payload["data_root"],
        arguments.get("project_id") or arguments.get("id"),
    )
    project_id = identity["od_project_id"]
    response = _opendesign_request(payload, f"/api/projects/{project_id}")
    project = response.get("project") if isinstance(response.get("project"), dict) else response
    if not isinstance(project, dict) or str(project.get("id") or "") != project_id:
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid project.", status_code=502)
    return {"project": project, **identity}


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
    identity = _resolve_project_identity(
        payload["data_root"],
        arguments.get("entity_id") or arguments.get("project_id"),
    )
    project_id = identity["od_project_id"]
    try:
        project = get_project(payload, {"project_id": project_id})["project"]
    except DesignStudioError as error:
        if error.error == "project_not_found":
            return {"entity_type": "design_project", "entity_id": project_id, "exists": False}
        raise
    return {"exists": True, **_opendesign_reference_item(payload, project), **identity}


def reference_summarize(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded summary for one OpenDesign project reference."""
    resolved = reference_resolve(payload, arguments)
    if not resolved.get("exists"):
        return {**resolved, "summary": ""}
    return resolved


def create_project(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Create one canonical project through the governed OpenDesign API."""
    name = _clean_text(arguments.get("name"), fallback="Untitled design")
    prompt = _clean_text(arguments.get("prompt"), fallback="")
    project_id = f"od_maverick_{uuid4().hex[:24]}"
    response = _opendesign_post(
        payload,
        "/api/projects",
        {
            "id": project_id,
            "name": name,
            "metadata": {
                "kind": "prototype",
                "maverickIntegration": "design-studio",
                **({"initialPrompt": prompt} if prompt else {}),
            },
            "skipDiscoveryBrief": True,
        },
    )
    project = response.get("project") if isinstance(response.get("project"), dict) else response
    if not isinstance(project, dict) or str(project.get("id") or "") != project_id:
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid project.", status_code=502)

    def select(state: dict[str, Any]) -> dict[str, Any]:
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(payload["data_root"], select)
    return {
        "project": project,
        "od_project_id": project_id,
        "state": _public_state(state),
    }


def import_from_storage(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Request a bounded Storage read for one canonical OpenDesign project."""
    data_root = payload["data_root"]
    identity = _resolve_project_identity(data_root, arguments.get("project_id"))
    project_id = identity["od_project_id"]
    project = get_project(payload, {"project_id": project_id})["project"]
    workspace_relative_path = _storage_path(arguments.get("workspace_relative_path"))
    if _should_request_storage_read(payload):
        return _request_storage_import(
            data_root=data_root,
            project_id=project_id,
            legacy_project_id=identity.get("legacy_project_id", ""),
            workspace_relative_path=workspace_relative_path,
            project=project,
        )
    raise DesignStudioError(
        "storage_dependency_unavailable",
        "Storage imports require the governed storage-read dependency.",
        status_code=503,
    )


def _request_storage_import(
    *,
    data_root: str,
    project_id: str,
    legacy_project_id: str,
    workspace_relative_path: str,
    project: dict[str, Any],
) -> dict[str, Any]:
    import_id = f"import_{uuid4().hex[:12]}"
    requested_at = utc_now()
    import_record = {
        "import_id": import_id,
        "od_project_id": project_id,
        **({"legacy_project_id": legacy_project_id} if legacy_project_id else {}),
        "status": "pending",
        "workspace_relative_path": workspace_relative_path,
        "name": Path(workspace_relative_path).name,
        "size_bytes": 0,
        "sha256": "",
        "media_type": "",
        "requested_at": requested_at,
        "imported_at": "",
        "error": "",
    }

    def apply_pending_import(state: dict[str, Any]) -> dict[str, Any]:
        _append_job(state["import_jobs"], import_record)
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(data_root, apply_pending_import)
    return {
        "import": import_record,
        "project": project,
        "od_project_id": project_id,
        **({"legacy_project_id": legacy_project_id} if legacy_project_id else {}),
        "state": _public_state(state),
        "dependency_backend_requests": [
            _storage_read_request(
                project_id=project_id,
                import_id=import_id,
                workspace_relative_path=workspace_relative_path,
            )
        ],
    }


def record_storage_import_result(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Upload a completed Storage read into OpenDesign and verify its bytes."""
    project_id = _opendesign_project_id(arguments.get("project_id"))
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
    digest = sha256(decoded).hexdigest()
    media_type = str(file_payload.get("media_type") or file_payload.get("mime_type") or "").strip()
    if not media_type:
        media_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    try:
        response = _opendesign_post(
            payload,
            f"/api/projects/{project_id}/files",
            {
                "name": file_name,
                "content": b64encode(decoded).decode("ascii"),
                "encoding": "base64",
                "overwrite": True,
            },
        )
    except DesignStudioError as error:
        return _mark_storage_import_failed(
            data_root=payload["data_root"],
            project_id=project_id,
            import_id=import_id,
            error=error.detail,
        )
    returned_file = response.get("file") if isinstance(response.get("file"), dict) else {}
    if str(returned_file.get("name") or "") != file_name or int(returned_file.get("size") or -1) != len(decoded):
        return _mark_storage_import_failed(
            data_root=payload["data_root"],
            project_id=project_id,
            import_id=import_id,
            error="OpenDesign returned mismatched file metadata after upload.",
        )
    try:
        verified = _opendesign_bytes_request(payload, f"/api/projects/{project_id}/raw/{file_name}")
    except DesignStudioError as error:
        return _mark_storage_import_failed(
            data_root=payload["data_root"],
            project_id=project_id,
            import_id=import_id,
            error=error.detail,
        )
    if sha256(verified).hexdigest() != digest:
        return _mark_storage_import_failed(
            data_root=payload["data_root"],
            project_id=project_id,
            import_id=import_id,
            error="OpenDesign read-back digest did not match the Storage source.",
        )
    imported_at = utc_now()
    imported = {
        "import_id": import_id,
        "od_project_id": project_id,
        "status": "imported",
        "workspace_relative_path": workspace_relative_path,
        "name": file_name,
        "size_bytes": len(decoded),
        "sha256": digest,
        "media_type": media_type,
        "requested_at": "",
        "imported_at": imported_at,
        "error": "",
    }

    def apply_result(state: dict[str, Any]) -> dict[str, Any]:
        existing = _find_job(state["import_jobs"], "import_id", import_id)
        if existing is None:
            _append_job(state["import_jobs"], imported)
        else:
            imported["requested_at"] = str(existing.get("requested_at") or "")
            if existing.get("legacy_project_id"):
                imported["legacy_project_id"] = existing["legacy_project_id"]
            existing.update(imported)
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(payload["data_root"], apply_result)
    item = _require_job(state["import_jobs"], "import_id", import_id, label="import")
    project = get_project(payload, {"project_id": project_id})["project"]
    return {
        "import": item,
        "project": project,
        "od_project_id": project_id,
        **({"legacy_project_id": item["legacy_project_id"]} if item.get("legacy_project_id") else {}),
        "state": _public_state(state),
    }


def export_to_storage(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Export one terminal run package and its OpenDesign project files."""
    data_root = payload["data_root"]
    identity = _resolve_project_identity(data_root, arguments.get("project_id"))
    project_id = identity["od_project_id"]
    run_id = validated_identifier(arguments.get("run_id"), label="OpenDesign run id")
    project = get_project(payload, {"project_id": project_id})["project"]
    try:
        correlation = store_for_payload(payload).get(run_id)
    except RuntimeBridgeError as error:
        raise DesignStudioError("run_not_found", str(error), status_code=404) from error
    if correlation.get("od_project_id") != project_id:
        raise DesignStudioError("run_project_mismatch", "The OpenDesign run does not belong to this project.")
    if correlation.get("status") not in {"succeeded", "failed", "canceled"}:
        raise DesignStudioError("run_not_terminal", "A terminal OpenDesign run is required for export.", status_code=409)
    result_package = correlation.get("result_package")
    if not isinstance(result_package, dict):
        raise DesignStudioError("run_result_missing", "The terminal OpenDesign result package is missing.", status_code=409)

    files_response = _opendesign_request(payload, f"/api/projects/{project_id}/files")
    raw_files = files_response.get("files")
    if not isinstance(raw_files, list) or any(not isinstance(item, dict) for item in raw_files):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid file list.", status_code=502)
    public_files = [_public_opendesign_file(item) for item in raw_files]
    file_names = sorted(item["path"] for item in public_files)
    if len(file_names) != len(set(file_names)):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned duplicate project files.", status_code=502)
    project_archive = b""
    verified_files: list[dict[str, Any]] = []
    if file_names:
        project_archive = _opendesign_bytes_post(
            payload,
            f"/api/projects/{project_id}/archive/batch",
            {"files": file_names},
        )
        verified_files = _verified_archive_files(project_archive, public_files)

    export_id = f"export_{uuid4().hex[:12]}"
    exported_at = utc_now()
    export_root = f"storage/generated/design-studio/{project_id}/{run_id}"
    artifacts: list[tuple[str, bytes, str, str]] = []
    if project_archive:
        artifacts.append(("project-files.zip", project_archive, "application/zip", "opendesign-project-files"))
    result_bytes = _json_bytes(result_package)
    artifacts.append(("result-package.json", result_bytes, "application/json", "opendesign-result-package"))
    artifact_manifest = [
        {
            "workspace_relative_path": f"{export_root}/{name}",
            "sha256": sha256(content).hexdigest(),
            "size_bytes": len(content),
            "media_type": media_type,
            "role": role,
        }
        for name, content, media_type, role in artifacts
    ]
    bundle = _opendesign_bundle_summary()
    runtime_status = _opendesign_runtime_status(data_root)
    manifest = {
        "schema_version": "1",
        "app_id": "design-studio",
        "opendesign_version": OPENDESIGN_VERSION,
        "opendesign_commit": OPENDESIGN_COMMIT,
        "export_id": export_id,
        "od_project_id": project_id,
        **({"legacy_project_id": identity["legacy_project_id"]} if identity.get("legacy_project_id") else {}),
        "od_run_id": run_id,
        "project": {"id": project_id, "name": str(project.get("name") or project_id)},
        "opendesign_files": verified_files,
        "artifacts": artifact_manifest,
        "provenance": {
            "provider_mode": "maverick-proxy",
            "runtime_session_id": str(correlation.get("runtime_session_id") or ""),
            "turn_id": str(correlation.get("turn_id") or ""),
            "stream_id": str(correlation.get("stream_id") or ""),
            "request_id": str(correlation.get("request_id") or ""),
            "correlation_id": str(correlation.get("correlation_id") or ""),
            "run_status": str(correlation.get("status") or ""),
            "run_updated_at": str(correlation.get("updated_at") or ""),
            "oci_reference": str(bundle.get("oci_reference") or ""),
            "oci_index_digest": str(bundle.get("oci_index_digest") or ""),
            "materialized_artifact_sha256": str(bundle.get("artifact_sha256") or ""),
            "runtime_artifact_sha256": str(runtime_status.get("runtime_artifact_sha256") or ""),
            "web_overlay_sha256": str(runtime_status.get("web_overlay_sha256") or ""),
            "storage_imports": [
                {
                    key: item.get(key)
                    for key in ("import_id", "workspace_relative_path", "name", "sha256", "size_bytes", "media_type")
                }
                for item in ensure_state(data_root).get("import_jobs", [])
                if item.get("od_project_id") == project_id and item.get("status") == "imported"
            ],
        },
    }
    manifest_bytes = _json_bytes(manifest)
    artifacts.append(("manifest.json", manifest_bytes, "application/json", "export-manifest"))
    expected_paths = [f"{export_root}/{name}" for name, _content, _media_type, _role in artifacts]
    export_record = {
        "export_id": export_id,
        "od_project_id": project_id,
        **({"legacy_project_id": identity["legacy_project_id"]} if identity.get("legacy_project_id") else {}),
        "od_run_id": run_id,
        "status": "pending",
        "workspace_relative_paths": expected_paths,
        "completed_workspace_relative_paths": [],
        "exported_at": exported_at,
        "completed_at": "",
        "error": "",
    }

    def apply_export(next_state: dict[str, Any]) -> dict[str, Any]:
        _append_job(next_state["export_jobs"], export_record)
        next_state["view_state"]["selected_project_id"] = project_id
        return next_state

    next_state = update_state(data_root, apply_export)
    return {
        "export": export_record,
        "project": project,
        **identity,
        "manifest": manifest,
        "state": _public_state(next_state),
        "dependency_backend_requests": [
            _storage_write_request(
                project_id=project_id,
                export_id=export_id,
                run_id=run_id,
                workspace_relative_path=f"{export_root}/{name}",
                content=content,
                artifact=role,
            )
            for name, content, _media_type, role in artifacts
        ],
    }


def record_storage_export_result(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Record the result of one Storage dependency-backend export write."""
    project_id = _opendesign_project_id(arguments.get("project_id"))
    export_id = _export_id(arguments.get("export_id"))
    workspace_relative_path = _storage_path(arguments.get("workspace_relative_path"))
    dependency_status = str(arguments.get("dependency_backend_status") or "").strip()
    dependency_result = arguments.get("dependency_backend_result") if isinstance(arguments.get("dependency_backend_result"), dict) else {}
    error = str(arguments.get("error") or "").strip()
    written_path = _storage_write_result_path(dependency_result) or workspace_relative_path
    if written_path != workspace_relative_path:
        raise DesignStudioError("storage_export_mismatch", "Storage wrote a different path than the export requested.")

    def apply_result(state: dict[str, Any]) -> dict[str, Any]:
        export = _require_job(state["export_jobs"], "export_id", export_id, label="export")
        if export.get("od_project_id") != project_id:
            raise DesignStudioError("storage_export_mismatch", "Storage export project identity changed.")
        if dependency_status != "completed":
            export["status"] = "failed"
            export["error"] = error or "Storage export write failed."
            return state
        completed = export.setdefault("completed_workspace_relative_paths", [])
        if workspace_relative_path not in completed:
            completed.append(workspace_relative_path)
        expected = set(export.get("workspace_relative_paths", []))
        if expected and expected.issubset(set(completed)) and export.get("status") != "failed":
            export["status"] = "exported"
            export["completed_at"] = utc_now()
            export["error"] = ""
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(payload["data_root"], apply_result)
    export = _require_job(state["export_jobs"], "export_id", export_id, label="export")
    return {"export": export, "od_project_id": project_id, "state": _public_state(state)}


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
    raw_project_id = str(arguments.get("project_id") or "").strip()
    identity: dict[str, str] = {}
    if raw_project_id:
        identity = _resolve_project_identity(payload["data_root"], raw_project_id)
        get_project(payload, {"project_id": identity["od_project_id"]})

    def update_view(state: dict[str, Any]) -> dict[str, Any]:
        if identity:
            state["view_state"]["selected_project_id"] = identity["od_project_id"]
        return state

    state = update_state(payload["data_root"], update_view)
    return {"view_state": state.get("view_state", {}), "state": _public_state(state), **identity}


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
    if _route_matches(route_path, "/api/app-config"):
        return _handle_app_config_route(payload, arguments, method=method)
    if _route_matches(route_path, "/api/attribution/claim"):
        return _handle_attribution_claim_route(method=method)
    if _route_matches(route_path, "/api/import/storage"):
        return _handle_storage_import_route(payload, arguments, method=method)
    if _route_matches(route_path, "/api/export/storage"):
        return _handle_storage_export_route(payload, arguments, method=method)
    if _route_matches(route_path, "/api/provider"):
        return _handle_provider_proxy_route(payload, arguments, method=method, route_path=route_path)
    if _route_matches(route_path, "/api/runs"):
        return _handle_runtime_bridge_route(payload, arguments, method=method, route_path=route_path)
    raise DesignStudioError(
        "sidecar_core_route_not_found",
        f"Design Studio does not implement handled sidecar route `{route_path}`.",
        status_code=404,
    )


def _handle_app_config_route(
    payload: dict[str, Any],
    arguments: dict[str, Any],
    *,
    method: str,
) -> dict[str, Any]:
    """Expose only non-secret OpenDesign preferences owned by Maverick."""
    if method == "GET":
        state = ensure_state(payload["data_root"])
        return {"status_code": 200, "json": {"config": state["opendesign_app_config"]}}
    if method != "PUT":
        raise DesignStudioError("method_not_allowed", "App config routes require GET or PUT.", status_code=405)
    body = _sidecar_core_body(arguments)
    allowed = {
        "onboardingCompleted",
        "agentId",
        "skillId",
        "designSystemId",
        "disabledSkills",
        "disabledDesignSystems",
        "telemetry",
        "allowSilentUpdates",
    }
    unexpected = sorted(set(body) - allowed)
    if unexpected:
        raise DesignStudioError(
            "app_config_field_not_allowed",
            f"OpenDesign app config field `{unexpected[0]}` is not governed by Maverick.",
            status_code=400,
        )
    updates: dict[str, Any] = {}
    if "onboardingCompleted" in body:
        if body["onboardingCompleted"] is not True:
            raise DesignStudioError(
                "app_config_value_not_allowed",
                "Maverick-owned runtime configuration keeps OpenDesign onboarding complete.",
                status_code=400,
            )
        updates["onboardingCompleted"] = True
    if "agentId" in body:
        if body["agentId"] not in {None, "maverick"}:
            raise DesignStudioError(
                "app_config_value_not_allowed",
                "OpenDesign execution is owned by the Maverick runtime bridge.",
                status_code=400,
            )
        updates["agentId"] = "maverick"
    for key in APP_CONFIG_SCALAR_KEYS:
        if key in body:
            value = body[key]
            if value is not None and (not isinstance(value, str) or not APP_CONFIG_ID_PATTERN.fullmatch(value)):
                raise DesignStudioError("app_config_invalid", f"OpenDesign app config field `{key}` is invalid.")
            updates[key] = value
    for key in APP_CONFIG_LIST_KEYS:
        if key in body:
            value = body[key]
            if (
                not isinstance(value, list)
                or len(value) > 256
                or any(not isinstance(item, str) or not APP_CONFIG_ID_PATTERN.fullmatch(item) for item in value)
            ):
                raise DesignStudioError("app_config_invalid", f"OpenDesign app config field `{key}` is invalid.")
            updates[key] = list(dict.fromkeys(value))
    if "telemetry" in body:
        telemetry = body["telemetry"]
        if not isinstance(telemetry, dict) or any(value is not False for value in telemetry.values()):
            raise DesignStudioError(
                "app_config_value_not_allowed",
                "OpenDesign telemetry remains disabled in the governed runtime.",
                status_code=400,
            )
        updates["telemetry"] = {"metrics": False, "content": False, "artifactManifest": False}
    if "allowSilentUpdates" in body:
        if body["allowSilentUpdates"] is not False:
            raise DesignStudioError(
                "app_config_value_not_allowed",
                "OpenDesign updates require a verified Maverick artifact.",
                status_code=400,
            )
        updates["allowSilentUpdates"] = False

    def apply(state: dict[str, Any]) -> dict[str, Any]:
        state["opendesign_app_config"].update(updates)
        return state

    state = update_state(payload["data_root"], apply)
    return {"status_code": 200, "json": {"config": state["opendesign_app_config"]}}


def _handle_attribution_claim_route(*, method: str) -> dict[str, Any]:
    if method != "POST":
        raise DesignStudioError("method_not_allowed", "Attribution claim routes require POST.", status_code=405)
    return {
        "status_code": 200,
        "json": {
            "ok": True,
            "status": "invalid",
            "found": False,
            "pending": False,
            "merged": False,
            "sidecar_reached": False,
            "telemetry_enabled": False,
        },
    }


def _handle_runtime_bridge_route(
    payload: dict[str, Any],
    arguments: dict[str, Any],
    *,
    method: str,
    route_path: str,
) -> dict[str, Any]:
    try:
        parts = [part for part in route_path.split("/") if part]
        if parts == ["api", "runs"]:
            if method == "GET":
                runtime_payload = trusted_sidecar_runtime_metadata_payload(payload)
                return {
                    "status_code": 200,
                    "json": {"runs": [public_run(record) for record in store_for_payload(runtime_payload).list()]},
                }
            if method == "POST":
                return _create_runtime_bridge_run(payload, _sidecar_core_body(arguments))
            raise DesignStudioError("method_not_allowed", "Run collection routes require GET or POST.", status_code=405)
        if len(parts) not in {3, 4} or parts[:2] != ["api", "runs"]:
            raise DesignStudioError("run_route_not_found", "OpenDesign run route was not found.", status_code=404)
        run_id = validated_identifier(parts[2], label="OpenDesign run id")
        runtime_payload = trusted_sidecar_runtime_metadata_payload(payload)
        record = store_for_payload(runtime_payload).get(run_id)
        if len(parts) == 3:
            if method != "GET":
                raise DesignStudioError("method_not_allowed", "Run status routes require GET.", status_code=405)
            return {"status_code": 200, "json": public_run(record)}
        operation = parts[3]
        if operation == "events" and method == "GET":
            last_event_id = str(payload.get("headers", {}).get("last-event-id") or "0")
            try:
                after_sequence = max(0, int(last_event_id))
            except ValueError as exc:
                raise DesignStudioError("last_event_id_invalid", "Last-Event-ID must be an integer.") from exc
            if not record.get("stream_id"):
                raise DesignStudioError("run_stream_pending", "Runtime stream is not bound yet.", status_code=409)
            return {
                "runtime_stream_response": {
                    "status_code": 200,
                    "stream_id": record["stream_id"],
                    "after_sequence": after_sequence,
                    "callback": {
                        "action": "runtime_bridge.translate_events",
                        "payload": {"od_run_id": run_id},
                    },
                }
            }
        if operation == "cancel" and method == "POST":
            if record["status"] in {"succeeded", "failed", "canceled"}:
                return {"status_code": 200, "json": public_run(record)}
            if not record.get("turn_id"):
                raise DesignStudioError("run_cancel_pending", "Runtime turn is not bound yet.", status_code=409)
            updated = mark_cancel_requested(runtime_payload, run_id)
            return {
                "status_code": 200,
                "json": public_run(updated),
                "runtime_turn_interrupt_requests": [
                    {
                        "turn_id": record["turn_id"],
                        "reason": "Canceled from the owning app run.",
                        "result_visibility": "internal",
                    }
                ],
            }
        if operation == "result-package" and method == "GET":
            result_package = record.get("result_package")
            if not isinstance(result_package, dict):
                if record["status"] not in {"succeeded", "failed", "canceled"}:
                    raise DesignStudioError("run_not_terminal", "Run result package is not ready.", status_code=409)
                result_package = build_result_package(record, files=[])
            return {"status_code": 200, "json": result_package}
        raise DesignStudioError("run_route_not_found", "OpenDesign run route was not found.", status_code=404)
    except RuntimeBridgeError as error:
        raise DesignStudioError("runtime_bridge_failed", str(error), status_code=409) from error


def _create_runtime_bridge_run(payload: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    project_id = validated_identifier(body.get("projectId"), label="OpenDesign project id")
    conversation_id = validated_identifier(body.get("conversationId"), label="OpenDesign conversation id")
    assistant_message_id = validated_identifier(
        body.get("assistantMessageId"),
        label="OpenDesign assistant message id",
    )
    client_request_id = str(body.get("clientRequestId") or "").strip()
    message = str(body.get("message") or body.get("currentPrompt") or "").strip()
    if not message:
        raise DesignStudioError("run_message_required", "OpenDesign run requires a message.")
    if len(message.encode("utf-8")) > 1_000_000:
        raise DesignStudioError("run_message_too_large", "OpenDesign run message is too large.", status_code=413)
    project_response = _opendesign_request(payload, f"/api/projects/{project_id}")
    project = project_response.get("project")
    if not isinstance(project, dict) or str(project.get("id") or "") != project_id:
        raise DesignStudioError("project_not_found", "The OpenDesign project was not found.", status_code=404)
    conversations_response = _opendesign_request(payload, f"/api/projects/{project_id}/conversations")
    conversations = conversations_response.get("conversations")
    if not isinstance(conversations, list) or not any(
        isinstance(item, dict) and str(item.get("id") or "") == conversation_id
        for item in conversations
    ):
        raise DesignStudioError("conversation_not_found", "The OpenDesign conversation was not found.", status_code=404)
    record, inserted = reserve_run(
        payload,
        project_id=project_id,
        conversation_id=conversation_id,
        assistant_message_id=assistant_message_id,
        client_request_id=client_request_id,
        agent_id="maverick",
    )
    response = {
        "runId": record["od_run_id"],
        "conversationId": record["od_conversation_id"],
        "assistantMessageId": record["assistant_message_id"],
    }
    if not inserted:
        return {"status_code": 202, "json": response}
    binding = binding_store_for_payload(payload).get(
        str(payload.get("workspace_id") or ""),
        project_id,
        conversation_id,
    )
    project_root = project_root_relative_to_app_data(payload, project_id)
    runtime_request = {
        "request_id": record["request_id"],
        "idempotency_key": record["idempotency_key"],
        "create_stream": True,
        "result_visibility": "public" if body.get("resultVisibility") == "public" else "internal",
        "agent_id": "chat",
        "agent_type_id": "chat",
        "agent_label": "Maverick Design Runtime",
        "title": str(body.get("threadTitle") or f"Design run {record['od_run_id']}")[:160],
        "project_id": project_id,
        "requested_mode": "sandbox",
        "system_prompt": _runtime_system_prompt(str(body.get("sessionMode") or "design")),
        "input_text": message,
        "project_root": {"scope": "app_data", "relative_path": project_root},
        "callback": {
            "action": "runtime_bridge.record_submission",
            "payload": {"od_run_id": record["od_run_id"]},
        },
    }
    if binding is not None:
        runtime_request["runtime_session_id"] = binding["runtime_session_id"]
    attachments = body.get("attachments")
    if isinstance(attachments, list):
        runtime_request["attachments"] = attachments
    app_references = body.get("appReferences")
    if isinstance(app_references, list):
        runtime_request["app_references"] = app_references
    return {
        "status_code": 202,
        "json": response,
        "runtime_session_requests": [runtime_request],
    }


def _runtime_system_prompt(session_mode: str) -> str:
    mode = session_mode if session_mode in {"chat", "plan", "design"} else "design"
    mode_instruction = {
        "chat": "Discuss the design and answer questions; edit files only when explicitly requested.",
        "plan": "Produce a concrete implementation plan before making any project-file changes.",
        "design": "Create or update project files needed to satisfy the user request.",
    }[mode]
    return (
        "Work only inside the current OpenDesign project directory. "
        f"OpenDesign session mode is {mode}. {mode_instruction} "
        "Do not inspect credentials, runtime homes, or paths outside this directory."
    )


def runtime_bridge_callback(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return record_submission(payload, arguments)
    except RuntimeBridgeError as error:
        raise DesignStudioError("runtime_bridge_callback_failed", str(error), status_code=409) from error


def runtime_bridge_translate(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return translate_stream_events(payload, arguments)
    except RuntimeBridgeError as error:
        raise DesignStudioError("runtime_bridge_translation_failed", str(error), status_code=409) from error


def cleanup_runtime_sessions(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Remove app-owned correlation metadata during trusted core cleanup."""
    if payload.get("effective_mode") != "full-access" or payload.get("user_id") is not None:
        raise DesignStudioError(
            "runtime_cleanup_forbidden",
            "Runtime cleanup is available only to the trusted platform cleanup flow.",
            status_code=403,
        )
    raw_session_ids = arguments.get("runtime_session_ids")
    if not isinstance(raw_session_ids, list):
        raise DesignStudioError(
            "runtime_session_ids_invalid",
            "runtime_session_ids must be a list of runtime session identifiers.",
        )
    session_ids: list[str] = []
    seen_session_ids: set[str] = set()
    for item in raw_session_ids:
        try:
            session_id = validated_identifier(item, label="runtime session id")
        except RuntimeBridgeError as error:
            raise DesignStudioError("runtime_session_ids_invalid", str(error)) from error
        if session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)
        session_ids.append(session_id)
    try:
        store = cleanup_store_for_payload(payload)
        deleted = 0 if store is None else store.delete_for_runtime_sessions(set(session_ids))
        binding_store = cleanup_binding_store_for_payload(payload)
        deleted_bindings = 0 if binding_store is None else binding_store.delete_for_runtime_sessions(set(session_ids))
    except RuntimeBridgeError as error:
        raise DesignStudioError("runtime_cleanup_failed", str(error), status_code=409) from error
    return {
        "cleaned_runtime_session_ids": session_ids,
        "deleted_runtime_correlations": deleted,
        "deleted_conversation_bindings": deleted_bindings,
    }


def runtime_bridge_terminal(payload: dict[str, Any], arguments: dict[str, Any], *, event_type: str) -> dict[str, Any]:
    runtime_session_id = str(arguments.get("runtime_session_id") or payload.get("runtime_session_id") or "")
    turn_id = str(arguments.get("turn_id") or payload.get("turn_id") or "")
    runtime_event_id = str(arguments.get("runtime_event_id") or "")
    files: list[dict[str, Any]] = []
    try:
        runtime_event_id = validated_identifier(runtime_event_id, label="runtime event id")
        store = store_for_payload(payload)
        correlation = store.find_by_runtime(runtime_session_id, turn_id)
        if correlation is not None:
            processed_event_id = str(correlation.get("terminal_runtime_event_id") or "")
            if processed_event_id:
                return {"correlation": correlation, "terminal_package_written": True}
            response = _opendesign_json_request(payload, f"/api/projects/{correlation['od_project_id']}/files")
            raw_files = response.get("files") if isinstance(response, dict) and isinstance(response.get("files"), list) else response
            if isinstance(raw_files, list):
                files = [item for item in raw_files if isinstance(item, dict)]
            _upsert_opendesign_assistant_terminal_message(
                payload,
                correlation,
                event_type=event_type,
                output_text=str(arguments.get("output_text") or ""),
                failure_reason=str(arguments.get("failure_reason") or ""),
            )
        updated = record_terminal(
            payload,
            runtime_session_id=runtime_session_id,
            turn_id=turn_id,
            event_type=event_type,
            runtime_event_id=runtime_event_id,
            files=files,
        )
    except (RuntimeBridgeError, DesignStudioError) as error:
        raise DesignStudioError("runtime_bridge_terminal_failed", str(error), status_code=409) from error
    return {"correlation": updated or {}, "terminal_package_written": bool(updated)}


def chat_capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    """Describe only actions exposed by the source-app chat contract."""
    return {
        "source_app_id": str(payload.get("app_id") or "design-studio"),
        "label": "OpenDesign",
        "modes": ["chat", "plan", "design"],
    }


def chat_list_conversations(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = validated_identifier(
        arguments.get("od_project_id") or arguments.get("project_id"),
        label="OpenDesign project id",
    )
    response = _opendesign_request(payload, f"/api/projects/{project_id}/conversations")
    conversations = response.get("conversations")
    if not isinstance(conversations, list) or any(not isinstance(item, dict) for item in conversations):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned invalid conversations.", status_code=502)
    bindings = binding_store_for_payload(payload)
    workspace_id = str(payload.get("workspace_id") or "")
    return {
        "od_project_id": project_id,
        "conversations": [
            {
                **conversation,
                "maverick_binding": bindings.get(workspace_id, project_id, str(conversation.get("id") or "")),
            }
            for conversation in conversations
            if str(conversation.get("id") or "")
        ],
    }


def chat_create_conversation(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = validated_identifier(
        arguments.get("od_project_id") or arguments.get("project_id"),
        label="OpenDesign project id",
    )
    mode = _chat_session_mode(arguments.get("session_mode") or arguments.get("mode"))
    title = str(arguments.get("title") or "New design conversation").strip()[:160] or "New design conversation"
    response = _opendesign_post(
        payload,
        f"/api/projects/{project_id}/conversations",
        {"title": title, "sessionMode": mode},
    )
    conversation = response.get("conversation") if isinstance(response.get("conversation"), dict) else response
    conversation_id = validated_identifier(conversation.get("id"), label="OpenDesign conversation id")
    return {"od_project_id": project_id, "od_conversation_id": conversation_id, "conversation": conversation}


def chat_submit_turn(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    runtime_session_id = str(arguments.get("runtime_session_id") or "").strip()
    existing_binding = None
    if runtime_session_id:
        existing_binding = binding_store_for_payload(payload).find_by_runtime(
            str(payload.get("workspace_id") or ""),
            runtime_session_id,
        )
    project_id = validated_identifier(
        arguments.get("od_project_id")
        or arguments.get("project_id")
        or (existing_binding or {}).get("od_project_id"),
        label="OpenDesign project id",
    )
    message = str(arguments.get("message") or arguments.get("input_text") or "").strip()
    if not message:
        raise DesignStudioError("chat_message_required", "OpenDesign chat requires a message.")
    if len(message.encode("utf-8")) > 1_000_000:
        raise DesignStudioError("chat_message_too_large", "OpenDesign chat message is too large.", status_code=413)
    project_response = _opendesign_request(payload, f"/api/projects/{project_id}")
    project = project_response.get("project") if isinstance(project_response.get("project"), dict) else project_response
    if not isinstance(project, dict) or str(project.get("id") or "") != project_id:
        raise DesignStudioError("project_not_found", "The OpenDesign project was not found.", status_code=404)
    mode = _chat_session_mode(arguments.get("session_mode") or arguments.get("mode"))
    conversation_id = str(
        arguments.get("od_conversation_id")
        or arguments.get("conversation_id")
        or (existing_binding or {}).get("od_conversation_id")
        or ""
    ).strip()
    if conversation_id:
        conversation_id = validated_identifier(conversation_id, label="OpenDesign conversation id")
        _require_opendesign_conversation(payload, project_id, conversation_id)
    else:
        created = chat_create_conversation(
            payload,
            {
                "od_project_id": project_id,
                "title": str(arguments.get("thread_title") or message)[:80],
                "session_mode": mode,
            },
        )
        conversation_id = str(created["od_conversation_id"])
    now_ms = int(time() * 1000)
    user_message_id = f"msg_{uuid4().hex}"
    assistant_message_id = f"msg_{uuid4().hex}"
    _upsert_opendesign_message(
        payload,
        project_id,
        conversation_id,
        user_message_id,
        {
            "id": user_message_id,
            "role": "user",
            "content": message,
            "sessionMode": mode,
            "createdAt": now_ms,
        },
    )
    _upsert_opendesign_message(
        payload,
        project_id,
        conversation_id,
        assistant_message_id,
        {
            "id": assistant_message_id,
            "role": "assistant",
            "content": "",
            "agentId": "maverick",
            "agentName": "Maverick Design Runtime",
            "runStatus": "queued",
            "sessionMode": mode,
            "createdAt": now_ms,
        },
    )
    bridge = _create_runtime_bridge_run(
        payload,
        {
            "projectId": project_id,
            "conversationId": conversation_id,
            "assistantMessageId": assistant_message_id,
            "clientRequestId": str(arguments.get("client_message_id") or uuid4()),
            "message": message,
            "sessionMode": mode,
            "threadTitle": str(arguments.get("thread_title") or project.get("name") or "OpenDesign")[:160],
            "resultVisibility": "public",
            "attachments": arguments.get("attachments"),
            "appReferences": arguments.get("app_references"),
        },
    )
    bridge_json = bridge.get("json") if isinstance(bridge.get("json"), dict) else {}
    bridge["json"] = {
        **bridge_json,
        "source_app_id": str(payload.get("app_id") or "design-studio"),
        "od_project_id": project_id,
        "od_conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "session_mode": mode,
    }
    return bridge


def chat_cancel_turn(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    runtime_session_id = validated_identifier(arguments.get("runtime_session_id"), label="runtime session id")
    turn_id = validated_identifier(arguments.get("turn_id"), label="runtime turn id")
    correlation = store_for_payload(payload).find_by_runtime(runtime_session_id, turn_id)
    if correlation is None:
        raise DesignStudioError("chat_turn_not_found", "The OpenDesign runtime turn was not found.", status_code=404)
    updated = mark_cancel_requested(payload, str(correlation["od_run_id"]))
    return {
        "status_code": 200,
        "json": {"run": public_run(updated)},
        "runtime_turn_interrupt_requests": [
            {
                "turn_id": turn_id,
                "reason": "Canceled from Maverick Chat for OpenDesign.",
                "result_visibility": "public",
            }
        ],
    }


def chat_retry_turn(payload: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    retry_arguments = dict(arguments)
    retry_arguments["client_message_id"] = str(arguments.get("client_message_id") or f"retry-{uuid4()}")
    return chat_submit_turn(payload, retry_arguments)


def _chat_session_mode(value: object) -> str:
    mode = str(value or "design").strip().lower()
    if mode not in {"chat", "plan", "design"}:
        raise DesignStudioError("chat_mode_invalid", "OpenDesign mode must be chat, plan, or design.")
    return mode


def _require_opendesign_conversation(payload: dict[str, Any], project_id: str, conversation_id: str) -> dict[str, Any]:
    conversations = chat_list_conversations(payload, {"od_project_id": project_id})["conversations"]
    for conversation in conversations:
        if str(conversation.get("id") or "") == conversation_id:
            return conversation
    raise DesignStudioError("conversation_not_found", "The OpenDesign conversation was not found.", status_code=404)


def _upsert_opendesign_message(
    payload: dict[str, Any],
    project_id: str,
    conversation_id: str,
    message_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    return _opendesign_put(
        payload,
        f"/api/projects/{project_id}/conversations/{conversation_id}/messages/{message_id}",
        body,
    )


def _upsert_opendesign_assistant_terminal_message(
    payload: dict[str, Any],
    correlation: dict[str, Any],
    *,
    event_type: str,
    output_text: str,
    failure_reason: str,
) -> None:
    status = "completed" if event_type == "runtime.turn.completed" else "canceled" if event_type == "runtime.turn.cancelled" else "failed"
    content = output_text.strip()
    if not content and failure_reason.strip():
        content = failure_reason.strip()
    _upsert_opendesign_message(
        payload,
        str(correlation["od_project_id"]),
        str(correlation["od_conversation_id"]),
        str(correlation["assistant_message_id"]),
        {
            "id": str(correlation["assistant_message_id"]),
            "role": "assistant",
            "content": content,
            "agentId": "maverick",
            "agentName": "Maverick Design Runtime",
            "runId": str(correlation["od_run_id"]),
            "runStatus": status,
            "endedAt": int(time() * 1000),
        },
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
    if action == "resolve_launch_target":
        return resolve_launch_target(payload, arguments)
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
    if action == "chat.capabilities":
        return chat_capabilities(payload)
    if action == "chat.list_conversations":
        return chat_list_conversations(payload, arguments)
    if action == "chat.create_conversation":
        return chat_create_conversation(payload, arguments)
    if action == "chat.submit_turn":
        return chat_submit_turn(payload, arguments)
    if action == "chat.cancel_turn":
        return chat_cancel_turn(payload, arguments)
    if action == "chat.retry_turn":
        return chat_retry_turn(payload, arguments)
    if action == "runtime_bridge.record_submission":
        return runtime_bridge_callback(payload, arguments)
    if action == "runtime_bridge.translate_events":
        return runtime_bridge_translate(payload, arguments)
    if action == "runtime.cleanup_sessions":
        return cleanup_runtime_sessions(payload, arguments)
    if action in {
        "runtime.turn.completed",
        "runtime.turn.failed",
        "runtime.turn.cancelled",
        "runtime.turn.timed-out",
    }:
        return runtime_bridge_terminal(payload, arguments, event_type=action)
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
        "view_state": state.get("view_state", {}),
        "opendesign_app_config": state.get("opendesign_app_config", {}),
        "import_jobs": state.get("import_jobs", []),
        "export_jobs": state.get("export_jobs", []),
        "lifecycle": state.get("lifecycle", {}),
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
    web_overlay = payload.get("web_overlay")
    valid = (
        payload.get("schema_version") == "2"
        and payload.get("opendesign_version") == OPENDESIGN_VERSION
        and payload.get("opendesign_commit") == OPENDESIGN_COMMIT
        and isinstance(active, dict)
        and active.get("od_version") == OPENDESIGN_VERSION
        and isinstance(active.get("runtime_artifact_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", active["runtime_artifact_sha256"]) is not None
        and isinstance(active.get("web_overlay_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", active["web_overlay_sha256"]) is not None
        and payload.get("runtime_artifact_sha256") == active["runtime_artifact_sha256"]
        and payload.get("web_overlay_sha256") == active["web_overlay_sha256"]
        and isinstance(bundle, dict)
        and bundle.get("location") == "verified_registry"
        and bundle.get("relative_path") == active["runtime_artifact_sha256"]
        and isinstance(web_overlay, dict)
        and web_overlay.get("location") == "verified_registry"
        and web_overlay.get("relative_path") == active["web_overlay_sha256"]
    )
    if not valid:
        return {"bundle_configured": False, "mode": "invalid-status", "detail": "", "active": {}}
    return {
        "bundle_configured": bool(payload.get("bundle_configured")),
        "mode": str(payload.get("mode") or "unknown"),
        "detail": str(payload.get("detail") or ""),
        "runtime_artifact_sha256": active["runtime_artifact_sha256"],
        "web_overlay_sha256": active["web_overlay_sha256"],
        "active": {
            "runtime_artifact_sha256": active["runtime_artifact_sha256"],
            "web_overlay_sha256": active["web_overlay_sha256"],
            "od_version": active["od_version"],
            "data_generation": str(active.get("data_generation") or ""),
        },
    }


def _find_job(jobs: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    return next((item for item in jobs if item.get(key) == value), None)


def _append_job(jobs: list[dict[str, Any]], item: dict[str, Any]) -> None:
    jobs.append(item)
    if len(jobs) > MAX_JOB_RECORDS:
        del jobs[:-MAX_JOB_RECORDS]


def _require_job(
    jobs: list[dict[str, Any]],
    key: str,
    value: str,
    *,
    label: str,
) -> dict[str, Any]:
    item = _find_job(jobs, key, value)
    if item is None:
        raise DesignStudioError(f"{label}_not_found", f"Design {label} `{value}` was not found.")
    return item


def _resolve_project_identity(data_root: str, value: object) -> dict[str, str]:
    raw_project_id = str(value or "").strip()
    if not PROJECT_ID_PATTERN.fullmatch(raw_project_id):
        return {"od_project_id": _opendesign_project_id(raw_project_id)}
    mapping = _read_legacy_project_map(data_root)
    matches = [item for item in mapping if item.get("legacy_project_id") == raw_project_id]
    if len(matches) != 1:
        raise DesignStudioError(
            "legacy_project_not_mapped",
            f"Legacy project `{raw_project_id}` has no unique OpenDesign mapping.",
            status_code=404,
        )
    od_project_id = _opendesign_project_id(matches[0].get("od_project_id"))
    return {"od_project_id": od_project_id, "legacy_project_id": raw_project_id}


def _read_legacy_project_map(data_root: str) -> list[dict[str, Any]]:
    root = Path(data_root).resolve()
    mapping_root = root / "opendesign"
    if mapping_root.is_symlink():
        raise DesignStudioError("legacy_project_map_invalid", "Legacy project mapping directory cannot be a symlink.")
    try:
        resolved_mapping_root = mapping_root.resolve(strict=True)
    except FileNotFoundError:
        return []
    if resolved_mapping_root != mapping_root:
        raise DesignStudioError("legacy_project_map_invalid", "Legacy project mapping directory escapes app data.")
    path = mapping_root / "legacy-project-map.json"
    if not path.exists():
        return []
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise DesignStudioError("legacy_project_map_invalid", "Legacy project mapping cannot be opened.") from error
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_LEGACY_MAP_BYTES:
            raise DesignStudioError("legacy_project_map_invalid", "Legacy project mapping is not a bounded regular file.")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            raw = handle.read(MAX_LEGACY_MAP_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > MAX_LEGACY_MAP_BYTES:
        raise DesignStudioError("legacy_project_map_invalid", "Legacy project mapping exceeds its size limit.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DesignStudioError("legacy_project_map_invalid", "Legacy project mapping is not valid JSON.") from error
    mappings = payload.get("mappings") if isinstance(payload, dict) else None
    if not isinstance(mappings, list) or any(not isinstance(item, dict) for item in mappings):
        raise DesignStudioError("legacy_project_map_invalid", "Legacy project mapping has an invalid schema.")
    return mappings


def _opendesign_project_id(value: object) -> str:
    project_id = str(value or "").strip()
    if not OPENDESIGN_PROJECT_ID_PATTERN.fullmatch(project_id) or PROJECT_ID_PATTERN.fullmatch(project_id):
        raise DesignStudioError("invalid_opendesign_project_id", "A valid OpenDesign project id is required.")
    return project_id


def _opendesign_request(payload: dict[str, Any], path: str) -> dict[str, Any]:
    decoded = _opendesign_json_request(payload, path)
    if not isinstance(decoded, dict):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid response.", status_code=502)
    return decoded


def _opendesign_json_request(payload: dict[str, Any], path: str) -> Any:
    response = _opendesign_response(payload, "GET", path)
    return _decode_opendesign_json(response)


def _opendesign_post(payload: dict[str, Any], path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = _opendesign_response(payload, "POST", path, json_body=body)
    decoded = _decode_opendesign_json(response)
    if not isinstance(decoded, dict):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid response.", status_code=502)
    return decoded


def _opendesign_put(payload: dict[str, Any], path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = _opendesign_response(payload, "PUT", path, json_body=body)
    decoded = _decode_opendesign_json(response)
    if not isinstance(decoded, dict):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid response.", status_code=502)
    return decoded


def _opendesign_bytes_request(payload: dict[str, Any], path: str) -> bytes:
    return _opendesign_response(payload, "GET", path).body


def _opendesign_bytes_post(payload: dict[str, Any], path: str, body: dict[str, Any]) -> bytes:
    return _opendesign_response(payload, "POST", path, json_body=body).body


def _opendesign_response(
    payload: dict[str, Any],
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
):
    try:
        response = app_sidecar(payload, "opendesign").request(
            method,
            path,
            headers={"accept": "application/json" if json_body is not None or method == "GET" else "*/*"},
            json_body=json_body,
        )
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
    return response


def _decode_opendesign_json(response) -> Any:
    try:
        decoded = response.json()
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DesignStudioError(
            "opendesign_response_invalid",
            "OpenDesign returned invalid JSON.",
            status_code=502,
        ) from error
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
    return payload.get("surface") in {"backend", "sidecar_core_handler", "cli", "mcp"} and isinstance(
        payload.get("app_dependencies"), dict
    )


def _mark_storage_import_failed(
    *,
    data_root: str,
    project_id: str,
    import_id: str,
    error: str,
) -> dict[str, Any]:
    def apply_failure(state: dict[str, Any]) -> dict[str, Any]:
        item = _find_job(state["import_jobs"], "import_id", import_id)
        if item is not None:
            item["status"] = "failed"
            item["error"] = error
            item["imported_at"] = ""
        state["view_state"]["selected_project_id"] = project_id
        return state

    state = update_state(data_root, apply_failure)
    item = _find_job(state["import_jobs"], "import_id", import_id)
    return {"import": item or {}, "od_project_id": project_id, "state": _public_state(state)}


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


def _public_opendesign_file(item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or item.get("path") or "").strip()
    if not name or "\\" in name or "\x00" in name:
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid file path.", status_code=502)
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(part in {"", ".", ".."} for part in path.parts):
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an unsafe file path.", status_code=502)
    try:
        size = int(item.get("size"))
    except (TypeError, ValueError) as error:
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid file size.", status_code=502) from error
    if size < 0:
        raise DesignStudioError("opendesign_response_invalid", "OpenDesign returned an invalid file size.", status_code=502)
    return {
        "name": name,
        "path": name,
        "size_bytes": size,
        "media_type": str(item.get("mime") or "application/octet-stream"),
        "kind": str(item.get("kind") or "file"),
    }


def _verified_archive_files(archive_bytes: bytes, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expected = {item["path"]: item for item in files}
    try:
        with ZipFile(BytesIO(archive_bytes), "r") as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != set(expected):
                raise DesignStudioError(
                    "opendesign_archive_invalid",
                    "OpenDesign project archive does not match its file catalog.",
                    status_code=502,
                )
            if any(info.flag_bits & 0x1 for info in infos):
                raise DesignStudioError("opendesign_archive_invalid", "OpenDesign returned an encrypted archive.", status_code=502)
            total = sum(info.file_size for info in infos)
            if total > MAX_EXPORT_UNCOMPRESSED_BYTES:
                raise DesignStudioError("opendesign_archive_too_large", "OpenDesign project export exceeds 128 MiB.", status_code=413)
            verified: list[dict[str, Any]] = []
            for info in sorted(infos, key=lambda value: value.filename):
                metadata = expected[info.filename]
                if info.file_size != metadata["size_bytes"]:
                    raise DesignStudioError(
                        "opendesign_archive_invalid",
                        "OpenDesign archive file size does not match its catalog.",
                        status_code=502,
                    )
                content = archive.read(info)
                verified.append({**metadata, "sha256": sha256(content).hexdigest()})
            return verified
    except BadZipFile as error:
        raise DesignStudioError("opendesign_archive_invalid", "OpenDesign returned an invalid project archive.", status_code=502) from error


def _clean_text(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    return text[:500] if text else fallback


def _storage_write_request(
    *,
    project_id: str,
    export_id: str,
    run_id: str,
    workspace_relative_path: str,
    content: bytes,
    artifact: str,
) -> dict[str, Any]:
    return {
        "request_id": f"{export_id}-{artifact}",
        "dependency_alias": "storage-write",
        "body": {
            "action": "file.content.write",
            "workspace_relative_path": workspace_relative_path,
            "mode": "create",
            "content_base64": b64encode(content).decode("ascii"),
        },
        "callback": {
            "action": "record_storage_export_result",
            "payload": {
                "project_id": project_id,
                "export_id": export_id,
                "run_id": run_id,
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


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
