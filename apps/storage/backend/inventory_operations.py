"""Durable Storage mutation intents bridging atomic filesystem changes and SQLite."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from errors import StorageConflictError
from inventory import uses_sqlite
import inventory_indexed as indexed
from inventory_sqlite import InventoryIndex
from storage_mutation_lock import storage_mutation_lock


def _signature(path: Path):
    try:
        return list(indexed.file_signature(path.stat()))
    except FileNotFoundError:
        return None


def _hash(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _flush_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError('Storage mutation path escapes its root.')
    return path


def _finalize(data_root: Path, root: Path, operation: dict):
    kind, role = operation['kind'], operation['role']
    target = _path(root, operation['target'])
    if kind == 'write':
        return indexed.upsert_file_record(data_root=data_root, role=role, root=root, path=target,
            sha256=operation['sha256'], file_id=operation['file_id'])
    if kind == 'create_directory':
        return indexed.upsert_directory_record(data_root=data_root, role=role, root=root, path=target)
    if kind in ('move_file', 'move_directory'):
        method = indexed.move_folder_records if kind == 'move_directory' else indexed.move_file_record
        return method(data_root=data_root, role=role, root=root, old_relative_path=operation['source'], new_path=target)
    method = indexed.remove_folder_records if kind == 'delete_directory' else indexed.remove_file_record
    method(data_root=data_root, role=role, relative_path=operation['target'])
    return None


def _cleanup(index: InventoryIndex, root: Path, operation: dict) -> None:
    if operation.get('staged'):
        stage = _path(root, operation['staged'])
        if stage.is_dir():
            shutil.rmtree(stage)
        else:
            stage.unlink(missing_ok=True)
        _flush_directory(stage.parent)
    with index.transaction(write=True) as connection:
        connection.execute('DELETE FROM operations WHERE operation_id=?', (operation['id'],))


def recover_operations(data_root: Path, roots: dict[str, Path]) -> dict:
    """Idempotently finish committed filesystem changes or abandon untouched preimages."""
    index = InventoryIndex(data_root)
    recovered = 0
    with storage_mutation_lock(data_root):
        with index.transaction() as connection:
            operations = [json.loads(row[0]) for row in connection.execute('SELECT document FROM operations ORDER BY operation_id')]
        for operation in operations:
            if operation['role'] not in roots:
                continue
            root = roots[operation['role']].resolve()
            target = _path(root, operation['target'])
            current = _signature(target)
            kind = operation['kind']
            committed = False
            untouched = current == operation['before']
            if kind == 'write':
                committed = current is not None and _hash(target) == operation['sha256']
                staged = _path(root, operation['staged'])
                if not committed and untouched and staged.is_file() and _hash(staged) == operation['sha256']:
                    staged.replace(target)
                    _flush_directory(target.parent)
                    committed = True
            elif kind == 'create_directory':
                committed = current is not None and current[3:] == operation['staged_signature'][3:]
            elif kind.startswith('move_'):
                source = _path(root, operation['source'])
                previous_source = _signature(source)
                committed = previous_source is None and current is not None and current[3:] == operation['source_signature'][3:]
                untouched = untouched and previous_source == operation['source_signature']
            elif kind == 'delete_directory':
                staged = _signature(_path(root, operation['staged']))
                committed = current is None and (staged is None or staged[3:] == operation['before'][3:])
            elif kind == 'delete_file':
                committed = current is None
            if committed:
                _finalize(data_root, root, operation)
            elif not untouched:
                raise StorageConflictError(f"Interrupted Storage operation {operation['id']} conflicts with external changes.",
                    conflict='inventory_recovery_required')
            _cleanup(index, root, operation)
            recovered += 1
    return {'recovered': recovered}


def mutate(*, data_root: Path, role: str, root: Path, target: Path, kind: str,
           source: Path | None = None, payload: bytes | None = None,
           staged_file: Path | None = None, sha256: str = ''):
    """One app-owned boundary used by writes, uploads, moves and deletes."""
    if kind not in ('write', 'create_directory', 'delete_directory', 'move_file', 'move_directory', 'delete_file'):
        raise ValueError('Unsupported Storage mutation.')
    with storage_mutation_lock(data_root):
        if not uses_sqlite(data_root):
            return _legacy_mutate(data_root=data_root, role=role, root=root, target=target,
                kind=kind, source=source, payload=payload, staged_file=staged_file, sha256=sha256)
        index = InventoryIndex(data_root)
        # Keep the database open across the durable intent/finalization commits.
        # The default last-connection checkpoint then runs once, inside the fence.
        with index.connect(write=True):
            return _mutate_indexed(index=index, data_root=data_root, role=role, root=root,
                target=target, kind=kind, source=source, payload=payload,
                staged_file=staged_file, sha256=sha256)


def _mutate_indexed(*, index: InventoryIndex, data_root: Path, role: str, root: Path,
                    target: Path, kind: str, source: Path | None, payload: bytes | None,
                    staged_file: Path | None, sha256: str):
    root = root.resolve()
    target = _path(root, target.relative_to(root).as_posix())
    recover_operations(data_root, {role: root})
    with index.transaction() as connection:
        if connection.execute('SELECT 1 FROM operations LIMIT 1').fetchone():
            raise StorageConflictError('Storage is recovering an interrupted operation.', conflict='inventory_recovery_required')
        previous = index.by_path(connection, role, target.relative_to(root).as_posix())
    operation = {'id': uuid4().hex, 'kind': kind, 'role': role,
        'target': target.relative_to(root).as_posix(), 'before': _signature(target),
        'file_id': previous['file_id'] if previous else 'file_' + uuid4().hex,
        'sha256': sha256, 'source': source.relative_to(root).as_posix() if source else '',
        'source_signature': _signature(source) if source else None}
    stage = None
    if kind in ('write', 'create_directory', 'delete_directory'):
        stage = target.parent / ('.maverick-storage-write-' + operation['id'])
        operation['staged'] = stage.relative_to(root).as_posix()
        if kind == 'write':
            if staged_file is not None:
                # The durable intent must precede moving a resumable upload's bytes.
                operation['sha256'] = sha256 or _hash(staged_file)
            else:
                with stage.open('xb') as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                operation['sha256'] = sha256 or _hash(stage)
        elif kind == 'create_directory':
            stage.mkdir()
        operation['staged_signature'] = _signature(stage)
        _flush_directory(target.parent)
    with index.transaction(write=True) as connection:
        connection.execute('INSERT INTO operations VALUES (?,?)', (operation['id'], json.dumps(operation)))
    if kind in ('write', 'create_directory'):
        if kind == 'write' and staged_file is not None:
            staged_file.replace(stage)
            _flush_directory(staged_file.parent)
        stage.replace(target)
    elif kind.startswith('move_'):
        source.rename(target)
        _flush_directory(source.parent)
    elif kind == 'delete_directory':
        target.rename(stage)
    elif kind == 'delete_file':
        target.unlink()
    else:
        raise ValueError('Unsupported Storage mutation.')
    _flush_directory(target.parent)
    result = _finalize(data_root, root, operation)
    _cleanup(index, root, operation)
    return result


def _legacy_mutate(*, data_root, role, root, target, kind, source, payload, staged_file, sha256):
    # Temporary adapter for workspaces that have not explicitly cut over.
    import inventory_legacy as legacy
    if kind == 'write':
        if staged_file is not None:
            staged_file.replace(target)
        else:
            from store_files_paths import atomic_write_bytes
            atomic_write_bytes(target, payload)
        return legacy.upsert_file_record(data_root=data_root, role=role, root=root, path=target, sha256=sha256 or _hash(target))
    if kind == 'create_directory':
        target.mkdir()
        return legacy.upsert_directory_record(data_root=data_root, role=role, root=root, path=target)
    if kind.startswith('move_'):
        shutil.move(str(source), str(target))
        method = legacy.move_folder_records if kind == 'move_directory' else legacy.move_file_record
        return method(data_root=data_root, role=role, root=root, old_relative_path=source.relative_to(root).as_posix(), new_path=target)
    if kind == 'delete_directory':
        shutil.rmtree(target)
        legacy.remove_folder_records(data_root=data_root, role=role, relative_path=target.relative_to(root).as_posix())
    elif kind == 'delete_file':
        target.unlink()
        legacy.remove_file_record(data_root=data_root, role=role, relative_path=target.relative_to(root).as_posix())
    return None
