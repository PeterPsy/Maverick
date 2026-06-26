"""Storage app CLI entrypoint."""

from __future__ import annotations

from base64 import b64encode
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from errors import StorageValidationError, validation_error_payload
from limits import LOCAL_UPLOAD_SESSION_CHUNK_BYTES
from operations_manifest import STORAGE_ACTION_ALIASES
from service import app_events_for_action, handle_action, secret_lookup_for_drive_action
from storage_mime import normalize_content_type
from store_files_paths import normalize_write_mode, reference_from_payload


def _upload_local_file_payload(*, data_root: Path, uploaded_root: Path, generated_root: Path, body: dict) -> tuple[int, dict]:
    source = _local_source_path(
        body.get("source_path"),
        workspace_root=body.get("_workspace_root"),
        effective_mode=body.get("_effective_mode"),
    )
    mode = normalize_write_mode(body.get("mode"), operation="upload_local_file")
    confirm = body.get("confirm")
    role, folder_relative_path, file_name = _local_upload_target(body, source)
    content_type = normalize_content_type(body.get("content_type"), file_name=source.name)
    size_bytes = source.stat().st_size
    _ensure_local_upload_folder(
        data_root=data_root,
        uploaded_root=uploaded_root,
        generated_root=generated_root,
        role=role,
        folder_relative_path=folder_relative_path,
    )
    if size_bytes == 0:
        role, relative_path = reference_from_payload(
            role=role,
            relative_path=(Path(str(folder_relative_path or "")) / file_name).as_posix() if folder_relative_path else file_name,
            workspace_relative_path="",
        )
        status_code, result = handle_action(
            data_root,
            uploaded_root,
            generated_root,
            {
                "action": "file.content.write",
                "role": role,
                "relative_path": relative_path,
                "content_base64": "",
                "mode": mode,
                "confirm": confirm,
            },
        )
        return status_code, {
            **result,
            "status": "uploaded",
            "provider": "local",
            "source_file_name": source.name,
            "source_size_bytes": 0,
            "bytes_uploaded": 0,
        }

    _start_status, started = handle_action(
        data_root,
        uploaded_root,
        generated_root,
        {
            "action": "local_upload_session.start",
            "role": role,
            "folder_relative_path": folder_relative_path,
            "file_name": file_name,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "mode": mode,
            "confirm": confirm,
        },
    )
    session_id = str(started["upload_session"]["id"])
    offset = 0
    result = started
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(LOCAL_UPLOAD_SESSION_CHUNK_BYTES)
            if not chunk:
                break
            _chunk_status, result = handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "local_upload_session.chunk",
                    "local_upload_session_id": session_id,
                    "chunk_offset": offset,
                    "content_base64": b64encode(chunk).decode("ascii"),
                },
            )
            offset += len(chunk)
    return 200, {
        **result,
        "source_file_name": source.name,
        "source_size_bytes": size_bytes,
        "bytes_uploaded": offset,
    }


def _ensure_local_upload_folder(*, data_root: Path, uploaded_root: Path, generated_root: Path, role: str, folder_relative_path: str) -> None:
    folder = str(folder_relative_path or "").strip().strip("/")
    if not folder:
        return
    parent = ""
    for part in Path(folder).parts:
        try:
            handle_action(
                data_root,
                uploaded_root,
                generated_root,
                {
                    "action": "create_folder",
                    "role": role,
                    "parent_relative_path": parent,
                    "folder_name": part,
                },
            )
        except StorageValidationError as error:
            if "already exists" not in error.detail:
                raise
        parent = (Path(parent) / part).as_posix() if parent else part


def _local_source_path(raw_source: object, *, workspace_root: object, effective_mode: object) -> Path:
    value = str(raw_source or "").strip()
    if not value:
        raise StorageValidationError("source_path is required.", operation="upload_local_file")
    if "\x00" in value:
        raise StorageValidationError("source_path contains an invalid character.", operation="upload_local_file")
    source = Path(value).expanduser().resolve()
    if not source.is_file():
        raise StorageValidationError("source_path must point to a readable local file.", operation="upload_local_file")
    _ensure_sandbox_source_inside_workspace(
        source,
        workspace_root=workspace_root,
        effective_mode=effective_mode,
    )
    return source


def _ensure_sandbox_source_inside_workspace(source: Path, *, workspace_root: object, effective_mode: object) -> None:
    if str(effective_mode or "sandbox").strip().lower() == "full-access":
        return
    raw_root = str(workspace_root or "").strip()
    if not raw_root:
        raise StorageValidationError(
            "upload_local_file requires workspace_root when running in sandbox mode.",
            operation="upload_local_file",
        )
    root = Path(raw_root).expanduser().resolve()
    if source != root and root not in source.parents:
        raise StorageValidationError(
            "sandbox upload_local_file source_path must be inside the workspace root.",
            operation="upload_local_file",
        )


def _local_upload_target(body: dict, source: Path) -> tuple[str, str, str]:
    workspace_relative_path = str(body.get("workspace_relative_path") or "").strip()
    relative_path = str(body.get("relative_path") or "").strip()
    role = str(body.get("role") or "generated").strip()
    if workspace_relative_path or relative_path:
        role, resolved_relative_path = reference_from_payload(
            role=role,
            relative_path=relative_path,
            workspace_relative_path=workspace_relative_path,
        )
        target_relative = Path(resolved_relative_path)
        if not target_relative.name:
            raise StorageValidationError("workspace_relative_path must include a file name.", operation="upload_local_file")
        folder = "" if str(target_relative.parent) == "." else target_relative.parent.as_posix()
        return role, folder, target_relative.name
    return role, str(body.get("folder_relative_path") or "").strip().strip("/"), str(body.get("file_name") or source.name)


payload = json.loads(sys.stdin.read() or "{}")
arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
requested_action = str(arguments.get("action") or "operations.manifest")
body = {
    **arguments,
    "_app_secrets": payload.get("app_secrets", {}),
    "_surface": str(payload.get("surface") or "cli"),
    "_effective_mode": str(payload.get("effective_mode") or "sandbox"),
    "_workspace_root": str(payload.get("workspace_root") or ""),
    "action": STORAGE_ACTION_ALIASES.get(requested_action, requested_action),
}
if payload.get("surface") == "secret_selector":
    print(
        json.dumps(
            secret_lookup_for_drive_action(
                Path(payload["data_root"]),
                Path(payload["uploaded_storage_root"]),
                Path(payload["generated_storage_root"]),
                body,
            ),
            ensure_ascii=False,
        )
    )
    raise SystemExit(0)
try:
    data_root = Path(payload["data_root"])
    uploaded_root = Path(payload["uploaded_storage_root"])
    generated_root = Path(payload["generated_storage_root"])
    if body["action"] == "upload_local_file":
        status_code, result = _upload_local_file_payload(
            data_root=data_root,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
            body=body,
        )
    else:
        status_code, result = handle_action(data_root, uploaded_root, generated_root, body)
except StorageValidationError as error:
    status_code, result = 400, validation_error_payload(error)

response = {"status_code": status_code, "workspace_id": payload.get("workspace_id"), **result}
if status_code < 400:
    response["app_events"] = app_events_for_action(str(body.get("action") or "catalog"))
print(json.dumps(response, ensure_ascii=False))
