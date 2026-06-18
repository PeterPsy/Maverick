"""Storage-backed attachment helpers for Mail."""

from __future__ import annotations

from email.message import EmailMessage
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile

from database import connect, now_timestamp


MAX_OUTBOUND_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_OUTBOUND_TOTAL_BYTES = 25 * 1024 * 1024
FILE_ROLES = {"uploaded", "generated"}


def normalize_workspace_attachments(payload: dict[str, object]) -> list[dict[str, object]]:
    raw = payload.get("workspace_attachments")
    if raw is None:
        raw = payload.get("attachments")
    if raw in (None, ""):
        return []
    uploaded_root = _optional_root(payload.get("_uploaded_storage_root"))
    generated_root = _optional_root(payload.get("_generated_storage_root"))
    items = raw if isinstance(raw, list) else [raw]
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    total_bytes = 0
    for item in items:
        workspace_relative_path, filename = _attachment_input(item)
        role, relative_path, path = resolve_workspace_storage_file(
            workspace_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        canonical_path = f"storage/{role}/{relative_path}"
        if canonical_path in seen:
            continue
        seen.add(canonical_path)
        size_bytes = path.stat().st_size
        if size_bytes > MAX_OUTBOUND_ATTACHMENT_BYTES:
            raise ValueError(f"Attachment `{workspace_relative_path}` exceeds the {MAX_OUTBOUND_ATTACHMENT_BYTES} byte outbound limit")
        total_bytes += size_bytes
        if total_bytes > MAX_OUTBOUND_TOTAL_BYTES:
            raise ValueError(f"Outbound attachments exceed the {MAX_OUTBOUND_TOTAL_BYTES} byte total limit")
        attachment_name = _safe_display_filename(filename or path.name)
        normalized.append(
            {
                "workspace_relative_path": canonical_path,
                "role": role,
                "relative_path": relative_path,
                "filename": attachment_name,
                "content_type": mimetypes.guess_type(attachment_name)[0] or "application/octet-stream",
                "size_bytes": size_bytes,
                "sha256": _hash_file(path),
            }
        )
    return normalized


def attach_workspace_attachments(
    message: EmailMessage,
    draft: dict[str, object],
    *,
    uploaded_root: Path | None,
    generated_root: Path | None,
) -> list[dict[str, object]]:
    attachments = draft.get("workspace_attachments")
    if not isinstance(attachments, list) or not attachments:
        return []
    attached: list[dict[str, object]] = []
    total_bytes = 0
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        path_text = str(attachment.get("workspace_relative_path") or "").strip()
        _role, _relative_path, path = resolve_workspace_storage_file(
            path_text,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        size_bytes = path.stat().st_size
        if size_bytes > MAX_OUTBOUND_ATTACHMENT_BYTES:
            raise ValueError(f"Attachment `{path_text}` exceeds the {MAX_OUTBOUND_ATTACHMENT_BYTES} byte outbound limit")
        total_bytes += size_bytes
        if total_bytes > MAX_OUTBOUND_TOTAL_BYTES:
            raise ValueError(f"Outbound attachments exceed the {MAX_OUTBOUND_TOTAL_BYTES} byte total limit")
        content_type = str(attachment.get("content_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        maintype, _, subtype = content_type.partition("/")
        if not maintype or not subtype:
            maintype, subtype = "application", "octet-stream"
        payload = path.read_bytes()
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=str(attachment.get("filename") or path.name))
        attached.append({**attachment, "size_bytes": len(payload), "sha256": _hash_bytes(payload)})
    return attached


def resolve_workspace_storage_file(
    workspace_relative_path: str,
    *,
    uploaded_root: Path | None,
    generated_root: Path | None,
) -> tuple[str, str, Path]:
    role, relative_path = _storage_reference(workspace_relative_path)
    root = generated_root if role == "generated" else uploaded_root
    if root is None:
        raise ValueError(f"{role} storage root is unavailable")
    root = root.resolve()
    target = (root / Path(relative_path)).resolve()
    if root not in target.parents or not target.is_file():
        raise ValueError(f"Storage file `{workspace_relative_path}` was not found")
    return role, relative_path, target


def save_attachment_to_storage(
    data_root: Path,
    *,
    attachment_id: str,
    filename: str,
    content_type: str,
    attachment_bytes: bytes,
    generated_storage_root: Path | None,
    target_folder: object = None,
    mode: object = "versioned",
) -> dict[str, object]:
    if generated_storage_root is None:
        raise ValueError("save_to_storage requires generated storage from the platform entrypoint")
    root = generated_storage_root.resolve()
    folder_relative = _target_folder_relative(target_folder)
    target_dir = (root / folder_relative).resolve()
    if root != target_dir and root not in target_dir.parents:
        raise ValueError("Attachment target folder escapes storage/generated")
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_storage_filename(filename)
    legacy_default = target_folder in (None, "")
    requested_name = f"{_safe_id(attachment_id)}-{safe_name}" if legacy_default else safe_name
    requested_target = (target_dir / requested_name).resolve()
    if requested_target.parent != target_dir:
        raise ValueError("Attachment target path escaped target folder")
    write_mode = _write_mode(mode)
    target = _target_for_mode(requested_target, write_mode)
    previous_sha256 = _hash_file(target) if target.exists() and target.is_file() else ""
    _atomic_write_bytes(target, attachment_bytes)
    relative_path = target.relative_to(root).as_posix()
    sha256 = _hash_bytes(attachment_bytes)
    storage_ref = {
        "workspace_relative_path": f"storage/generated/{relative_path}",
        "filename": filename,
        "stored_filename": target.name,
        "content_type": content_type,
        "size_bytes": len(attachment_bytes),
        "sha256": sha256,
        "mode": write_mode,
        "previous_sha256": previous_sha256,
    }
    if target != requested_target:
        storage_ref["collision"] = "renamed"
    with connect(data_root) as db:
        db.execute(
            "UPDATE attachments SET storage_state = ?, storage_ref_json = ?, updated_at = ? WHERE id = ?",
            ("saved", json.dumps(storage_ref, ensure_ascii=True, sort_keys=True), now_timestamp(), attachment_id),
        )
    return storage_ref


def _attachment_input(item: object) -> tuple[str, str]:
    if isinstance(item, dict):
        workspace_relative_path = str(item.get("workspace_relative_path") or item.get("path") or "").strip()
        filename = str(item.get("filename") or item.get("name") or "").strip()
    else:
        workspace_relative_path = str(item or "").strip()
        filename = ""
    if not workspace_relative_path:
        raise ValueError("workspace attachment path is required")
    return workspace_relative_path, filename


def _storage_reference(workspace_relative_path: str) -> tuple[str, str]:
    parts = Path(str(workspace_relative_path or "").strip()).parts
    if len(parts) < 3 or parts[0] != "storage" or parts[1] not in FILE_ROLES:
        raise ValueError("Storage attachments must use storage/uploaded/... or storage/generated/... paths")
    relative_path = Path(*parts[2:])
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("Storage attachment path escapes storage root")
    return parts[1], relative_path.as_posix()


def _target_folder_relative(value: object) -> Path:
    text = str(value or "storage/generated/mail/attachments").strip().strip("/")
    if text.startswith("storage/generated/"):
        text = text.removeprefix("storage/generated/")
    elif text.startswith("storage/"):
        raise ValueError("Mail can save attachments only under storage/generated")
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("target_folder escapes storage/generated")
    return relative


def _write_mode(value: object) -> str:
    mode = str(value or "versioned").strip().lower()
    if mode not in {"create", "overwrite", "versioned"}:
        raise ValueError("mode must be create, overwrite, or versioned")
    return mode


def _target_for_mode(target: Path, mode: str) -> Path:
    if target.exists() and not target.is_file():
        raise ValueError("Attachment target path is not a file")
    if mode == "create" and target.exists():
        raise ValueError("Attachment target file already exists")
    if mode == "overwrite" and not target.exists():
        raise ValueError("Attachment target file does not exist")
    if mode == "versioned" and target.exists():
        return _versioned_path(target)
    return target


def _versioned_path(target: Path) -> Path:
    suffix = target.suffix
    stem = target.name[: -len(suffix)] if suffix else target.name
    for index in range(2, 10_000):
        candidate = target.with_name(f"{stem}.v{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("Could not allocate a versioned attachment path")


def _optional_root(value: object) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def _safe_display_filename(value: str) -> str:
    name = str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    return name or "attachment.bin"


def _safe_storage_filename(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", _safe_display_filename(value)).strip(".-")
    return name or "attachment.bin"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower() or "attachment"


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
