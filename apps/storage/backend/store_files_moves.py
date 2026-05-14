"""Storage move actions."""

from __future__ import annotations

from pathlib import Path
import shutil

from errors import StorageValidationError
from inventory import move_file_record, move_folder_records, upsert_directory_record, upsert_file_record
from store_files_paths import (
    is_system_upload_folder,
    reference_from_payload,
    resolve_storage_file,
    resolve_storage_folder,
    storage_root_for_role,
    storage_write_lock,
)

MAX_BATCH_MOVE_ITEMS = 500


def move_file_payload(*, role: str, relative_path: str, target_folder_relative_path: object, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        source = resolve_storage_file(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        target_folder = resolve_storage_folder(
            role=role,
            relative_path=target_folder_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        target = (target_folder / source.name).resolve()
        if root not in target.parents:
            raise StorageValidationError("Moved file must stay inside the selected storage root.")
        if target.exists() and target != source:
            raise StorageValidationError("A file or folder with that name already exists in the target folder.")
        if target == source:
            return {"file": upsert_file_record(data_root=data_root, role=role, root=root, path=source)}
        shutil.move(str(source), str(target))
        return {"file": move_file_record(data_root=data_root, role=role, root=root, old_relative_path=relative_path, new_path=target)}


def move_folder_payload(*, role: str, relative_path: object, target_folder_relative_path: object, data_root: Path, uploaded_root: Path, generated_root: Path) -> dict:
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        source = resolve_storage_folder(
            role=role,
            relative_path=relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        if source == root:
            raise StorageValidationError("Storage root folders cannot be moved.")
        source_relative = source.relative_to(root).as_posix()
        if is_system_upload_folder(role=role, relative_path=source_relative):
            raise StorageValidationError("Folder is not visible in Storage.")
        target_folder = resolve_storage_folder(
            role=role,
            relative_path=target_folder_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        target_folder_relative = "" if target_folder == root else target_folder.relative_to(root).as_posix()
        if target_folder_relative and is_system_upload_folder(role=role, relative_path=target_folder_relative):
            raise StorageValidationError("Target folder is not visible in Storage.")
        if target_folder == source or source in target_folder.parents:
            raise StorageValidationError("A folder cannot be moved into itself or one of its child folders.")
        target = (target_folder / source.name).resolve()
        if root not in target.parents:
            raise StorageValidationError("Moved folder must stay inside the selected storage root.")
        if target.exists() and target != source:
            raise StorageValidationError("A file or folder with that name already exists in the target folder.")
        if target == source:
            return {"folder": upsert_directory_record(data_root=data_root, role=role, root=root, path=source)}
        shutil.move(str(source), str(target))
        return {"folder": move_folder_records(data_root=data_root, role=role, root=root, old_relative_path=source_relative, new_path=target)}


def move_items_payload(
    *,
    role: str,
    files: object,
    folders: object,
    target_folder_relative_path: object,
    data_root: Path,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    file_references = _file_references(files)
    folder_references = _folder_references(folders)
    if not file_references and not folder_references:
        raise StorageValidationError("move_items requires at least one file or folder.")
    if len(file_references) + len(folder_references) > MAX_BATCH_MOVE_ITEMS:
        raise StorageValidationError(f"move_items supports at most {MAX_BATCH_MOVE_ITEMS} items.")
    root = storage_root_for_role(role=role, uploaded_root=uploaded_root, generated_root=generated_root).resolve()
    with storage_write_lock(data_root):
        target_folder = resolve_storage_folder(
            role=role,
            relative_path=target_folder_relative_path,
            uploaded_root=uploaded_root,
            generated_root=generated_root,
        )
        target_folder_relative = "" if target_folder == root else target_folder.relative_to(root).as_posix()
        if target_folder_relative and is_system_upload_folder(role=role, relative_path=target_folder_relative):
            raise StorageValidationError("Target folder is not visible in Storage.")
        top_level_folders = _top_level_folder_references(folder_references)
        top_level_files = _top_level_file_references(file_references, top_level_folders)
        file_entries = [
            _planned_file_move(
                item,
                role=role,
                root=root,
                target_folder=target_folder,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
            )
            for item in top_level_files
        ]
        folder_entries = [
            _planned_folder_move(
                item,
                role=role,
                root=root,
                target_folder=target_folder,
                uploaded_root=uploaded_root,
                generated_root=generated_root,
            )
            for item in top_level_folders
        ]
        _validate_batch_targets([*file_entries, *folder_entries])
        moved_files = [_execute_file_move(entry, data_root=data_root, root=root) for entry in file_entries]
        moved_folders = [_execute_folder_move(entry, data_root=data_root, root=root) for entry in folder_entries]
        return {"files": moved_files, "folders": moved_folders}


def _file_references(value: object) -> list[dict[str, str]]:
    return _references(value, kind="file")


def _folder_references(value: object) -> list[dict[str, str]]:
    return _references(value, kind="folder")


def _references(value: object, *, kind: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StorageValidationError(f"{kind}s must be an array.")
    if len(value) > MAX_BATCH_MOVE_ITEMS:
        raise StorageValidationError(f"{kind}s must contain at most {MAX_BATCH_MOVE_ITEMS} items.")
    references: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            raise StorageValidationError(f"Each moved {kind} must be an object.")
        role, relative_path = reference_from_payload(
            role=str(item.get("role") or ""),
            relative_path=str(item.get("relative_path") or ""),
            workspace_relative_path=str(item.get("workspace_relative_path") or ""),
        )
        key = (role, relative_path)
        if key in seen:
            continue
        references.append({"role": role, "relative_path": relative_path})
        seen.add(key)
    return references


def _top_level_folder_references(references: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in references:
        relative_path = item["relative_path"].strip("/")
        if not relative_path:
            raise StorageValidationError("Storage root folders cannot be moved.")
        if any(
            parent["role"] == item["role"]
            and parent["relative_path"] != item["relative_path"]
            and _relative_path_is_self_or_child(relative_path, parent["relative_path"])
            for parent in references
        ):
            continue
        result.append(item)
    return result


def _top_level_file_references(file_references: list[dict[str, str]], folder_references: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        item
        for item in file_references
        if not any(
            folder["role"] == item["role"]
            and _relative_path_is_self_or_child(item["relative_path"], folder["relative_path"])
            for folder in folder_references
        )
    ]


def _planned_file_move(
    item: dict[str, str],
    *,
    role: str,
    root: Path,
    target_folder: Path,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    if item["role"] != role:
        raise StorageValidationError("Files can only be moved within their current storage section.")
    source = resolve_storage_file(
        role=role,
        relative_path=item["relative_path"],
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    target = (target_folder / source.name).resolve()
    if root not in target.parents:
        raise StorageValidationError("Moved file must stay inside the selected storage root.")
    return {
        "kind": "file",
        "previous": _file_previous(role=role, relative_path=item["relative_path"]),
        "source": source,
        "target": target,
    }


def _planned_folder_move(
    item: dict[str, str],
    *,
    role: str,
    root: Path,
    target_folder: Path,
    uploaded_root: Path,
    generated_root: Path,
) -> dict:
    if item["role"] != role:
        raise StorageValidationError("Folders can only be moved within their current storage section.")
    source = resolve_storage_folder(
        role=role,
        relative_path=item["relative_path"],
        uploaded_root=uploaded_root,
        generated_root=generated_root,
    )
    if source == root:
        raise StorageValidationError("Storage root folders cannot be moved.")
    source_relative = source.relative_to(root).as_posix()
    if is_system_upload_folder(role=role, relative_path=source_relative):
        raise StorageValidationError("Folder is not visible in Storage.")
    if target_folder == source or source in target_folder.parents:
        raise StorageValidationError("A folder cannot be moved into itself or one of its child folders.")
    target = (target_folder / source.name).resolve()
    if root not in target.parents:
        raise StorageValidationError("Moved folder must stay inside the selected storage root.")
    return {
        "kind": "folder",
        "previous": _folder_previous(role=role, relative_path=source_relative),
        "source": source,
        "target": target,
    }


def _validate_batch_targets(entries: list[dict]) -> None:
    planned_targets: dict[Path, dict] = {}
    for entry in entries:
        target = entry["target"]
        source = entry["source"]
        existing = planned_targets.get(target)
        if existing is not None and existing["source"] != source:
            raise StorageValidationError("Multiple moved items would use the same target name.")
        planned_targets[target] = entry
        if target.exists() and target != source:
            raise StorageValidationError("A file or folder with that name already exists in the target folder.")


def _execute_file_move(entry: dict, *, data_root: Path, root: Path) -> dict:
    role = entry["previous"]["role"]
    relative_path = entry["previous"]["relative_path"]
    source = entry["source"]
    target = entry["target"]
    if target == source:
        record = upsert_file_record(data_root=data_root, role=role, root=root, path=source)
    else:
        shutil.move(str(source), str(target))
        record = move_file_record(data_root=data_root, role=role, root=root, old_relative_path=relative_path, new_path=target)
    return {"previous": entry["previous"], "file": record}


def _execute_folder_move(entry: dict, *, data_root: Path, root: Path) -> dict:
    role = entry["previous"]["role"]
    relative_path = entry["previous"]["relative_path"]
    source = entry["source"]
    target = entry["target"]
    if target == source:
        record = upsert_directory_record(data_root=data_root, role=role, root=root, path=source)
    else:
        shutil.move(str(source), str(target))
        record = move_folder_records(data_root=data_root, role=role, root=root, old_relative_path=relative_path, new_path=target)
    return {"previous": entry["previous"], "folder": record}


def _file_previous(*, role: str, relative_path: str) -> dict[str, str]:
    return {
        "role": role,
        "relative_path": relative_path,
        "workspace_relative_path": f"storage/{role}/{relative_path}",
    }


def _folder_previous(*, role: str, relative_path: str) -> dict[str, str]:
    return {
        "role": role,
        "relative_path": relative_path,
        "workspace_relative_path": f"storage/{role}" + (f"/{relative_path}" if relative_path else ""),
    }


def _relative_path_is_self_or_child(relative_path: str, prefix: str) -> bool:
    normalized_path = relative_path.strip("/")
    normalized_prefix = prefix.strip("/")
    return normalized_path == normalized_prefix or normalized_path.startswith(f"{normalized_prefix}/")
