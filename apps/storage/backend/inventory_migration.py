"""Explicit Storage inventory prepare/validate/cutover and lossless reverse export."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from inventory_sqlite import INDEX_FILE, SCHEMA_VERSION, InventoryIndex
from storage_mutation_lock import storage_mutation_lock


def initialize_inventory(data_root: Path) -> None:
    """Explicit installation of an empty index; existing JSON always needs prepare/cutover."""
    with storage_mutation_lock(data_root):
        if (data_root / 'inventory-store.json').exists():
            return
        if (data_root / 'files.json').exists():
            raise ValueError('Existing Storage metadata requires an explicit migration.')
        if (data_root / INDEX_FILE).exists():
            with InventoryIndex(data_root).transaction() as connection:
                if connection.execute('SELECT COUNT(*) FROM files').fetchone()[0]:
                    raise ValueError('An unselected nonempty Storage index requires explicit recovery.')
        else:
            InventoryIndex(data_root).initialize()
        _write_json(data_root / 'inventory-store.json', {'adapter': 'sqlite', 'schema_version': SCHEMA_VERSION})


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _records_digest(records: list[dict], key: str) -> str:
    identifiers = [record[key] for record in records]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f'Duplicate Storage {key}; resolve the source before migration.')
    return _digest(sorted(records, key=lambda record: record[key]))


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + f'.{uuid4().hex}.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o660)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _filesystem_digest(payload: dict, roots: dict[str, Path]) -> str:
    signatures = []
    for role, root in sorted(roots.items()):
        stat = root.stat()
        signatures.append((role, '', (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)))
    for record in [*payload['files'], *payload['directories']]:
        if record.get('provider', 'local') != 'local' or record.get('status') != 'active':
            continue
        root = roots[record['role']].resolve()
        target = root / record['relative_path']
        resolved = target.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError('Storage source path escapes its root.')
        try:
            stat = target.stat()
            signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)
        except FileNotFoundError:
            signature = None
        # Permission/I/O failures abort preparation, never imply deleted data.
        signatures.append((record['role'], record['relative_path'], signature))
    return _digest(signatures)


def _candidate(data_root: Path, migration_id: str) -> Path:
    if not migration_id.startswith('inventory-') or len(migration_id) != 42 or any(c not in '0123456789abcdef' for c in migration_id[10:]):
        raise ValueError('Invalid Storage migration id.')
    return data_root / 'migrations' / migration_id


def prepare_inventory(data_root: Path, *, uploaded_root: Path, generated_root: Path) -> dict:
    with storage_mutation_lock(data_root):
        from inventory import uses_sqlite
        if uses_sqlite(data_root):
            raise ValueError('Storage already uses SQLite; refuse a stale JSON migration.')
        marker_path = data_root / 'inventory-store.json'
        if marker_path.exists():
            _finish_retirement(data_root, json.loads(marker_path.read_text()))
        source = (data_root / 'files.json').read_bytes()
        payload = json.loads(source)
        if str(payload.get('schema_version')) != '1':
            raise ValueError('Unsupported Storage source schema.')
        files, directories = payload['files'], payload['directories']
        expected_files = _records_digest(files, 'file_id')
        expected_directories = _records_digest(directories, 'id')
        roots = {'uploaded': uploaded_root, 'generated': generated_root}
        filesystem_digest = _filesystem_digest(payload, roots)
        checks = {}
        for record in files:
            if record.get('provider', 'local') != 'local' or record.get('status') != 'active':
                continue
            try:
                path = roots[record['role']] / record['relative_path']
                stat = path.stat()
                if record.get('sha256'):
                    with path.open('rb') as handle:
                        if hashlib.file_digest(handle, 'sha256').hexdigest() != record['sha256']:
                            raise ValueError('A Storage content hash is stale; reconcile that file before migration.')
                checks[record['file_id']] = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)
            except FileNotFoundError:
                continue
        migration_id = 'inventory-' + uuid4().hex
        candidate_root = _candidate(data_root, migration_id)
        candidate_root.mkdir(parents=True)
        index = InventoryIndex(candidate_root)
        index.initialize()
        with index.transaction(write=True) as connection:
            for record in files:
                index.put_file(connection, record)
                if record['file_id'] in checks:
                    index.set_signature(connection, record['file_id'], checks[record['file_id']])
            for record in directories:
                index.put_directory(connection, record)
        backup = candidate_root / 'source.json'
        with backup.open('xb') as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        backup.chmod(0o440)
        manifest = {'migration_id': migration_id, 'status': 'prepared', 'source_schema': '1',
            'target_schema': SCHEMA_VERSION, 'sqlite_runtime': sqlite3.sqlite_version,
            'source_sha256': hashlib.sha256(source).hexdigest(), 'filesystem_digest': filesystem_digest,
            'file_count': len(files), 'directory_count': len(directories),
            'files_digest': expected_files, 'directories_digest': expected_directories}
        _write_json(candidate_root / 'manifest.json', manifest)
        return validate_inventory(data_root, migration_id)


def validate_inventory(data_root: Path, migration_id: str) -> dict:
    candidate_root = _candidate(data_root, migration_id)
    manifest = json.loads((candidate_root / 'manifest.json').read_text())
    _validate_index(InventoryIndex(candidate_root), manifest)
    return {**manifest, 'validated': True}


def _validate_index(index: InventoryIndex, manifest: dict) -> None:
    with index.transaction() as connection:
        integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
        files = [json.loads(row[0]) for row in connection.execute('SELECT document FROM files')]
        directories = [json.loads(row[0]) for row in connection.execute('SELECT document FROM directories')]
    if integrity != 'ok' or len(files) != manifest['file_count'] or len(directories) != manifest['directory_count']:
        raise ValueError('Storage migration integrity/count validation failed.')
    if _records_digest(files, 'file_id') != manifest['files_digest'] or _records_digest(directories, 'id') != manifest['directories_digest']:
        raise ValueError('Storage migration changed record identities or metadata.')


def cutover_inventory(data_root: Path, migration_id: str, *, uploaded_root: Path, generated_root: Path) -> dict:
    with storage_mutation_lock(data_root):
        marker_path = data_root / 'inventory-store.json'
        if marker_path.exists():
            marker = json.loads(marker_path.read_text())
            if marker.get('adapter') == 'sqlite':
                if marker.get('migration_id') != migration_id:
                    raise ValueError('Another Storage migration is already active.')
                return {'status': 'active', **marker}
        manifest = validate_inventory(data_root, migration_id)
        source = (data_root / 'files.json').read_bytes()
        roots = {'uploaded': uploaded_root, 'generated': generated_root}
        if hashlib.sha256(source).hexdigest() != manifest['source_sha256'] or _filesystem_digest(json.loads(source), roots) != manifest['filesystem_digest']:
            raise ValueError('Storage changed after preparation; prepare a fresh candidate.')
        if (data_root / INDEX_FILE).exists():
            # An interrupted promotion may already have installed the exact candidate.
            # Divergent data is never replaced by a retry.
            _validate_index(InventoryIndex(data_root), manifest)
        else:
            # Stage through the backup API and atomically promote only a complete DB.
            staged = _candidate(data_root, migration_id) / ('promotion-' + uuid4().hex + '.sqlite')
            InventoryIndex(_candidate(data_root, migration_id)).backup(staged)
            staged.replace(data_root / INDEX_FILE)
        with InventoryIndex(data_root).connect(write=True) as connection:
            if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                raise RuntimeError('Storage cutover requires WAL support.')
        _write_json(data_root / 'inventory-store.json', {'adapter': 'sqlite', 'schema_version': SCHEMA_VERSION,
            'migration_id': migration_id})
        return {**manifest, 'status': 'active', 'adapter': 'sqlite'}


def export_inventory(index: InventoryIndex) -> dict:
    with index.transaction() as connection:
        return {'schema_version': '1',
            'files': [json.loads(row[0]) for row in connection.execute('SELECT document FROM files ORDER BY file_id')],
            'directories': [json.loads(row[0]) for row in connection.execute('SELECT document FROM directories ORDER BY directory_id')],
            'updated_at': str(index.revision(connection))}


def backup_inventory(data_root: Path) -> dict:
    """Publish a verified standalone metadata snapshot, including committed WAL."""
    from inventory import uses_sqlite
    from inventory_queries import require_ready

    with storage_mutation_lock(data_root):
        if not uses_sqlite(data_root):
            raise ValueError('Storage inventory backup requires the selected SQLite adapter.')
        index = InventoryIndex(data_root)
        with index.transaction() as connection:
            require_ready(connection)
        backup_id = 'inventory-' + uuid4().hex
        backups = data_root / 'backups'
        backups.mkdir(parents=True, exist_ok=True)
        staging = backups / f'.{backup_id}.pending'
        staging.mkdir(mode=0o770)
        destination = backups / backup_id
        try:
            index.backup(staging / INDEX_FILE)
            # This standalone artifact never depends on sibling WAL/SHM files.
            connection = sqlite3.connect(staging / INDEX_FILE)
            try:
                if connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
                    raise RuntimeError('Storage backup could not finalize a standalone database.')
            finally:
                connection.close()
            payload = export_inventory(InventoryIndex(staging))
            manifest = {'owner': 'storage', 'backup_id': backup_id, 'schema_version': SCHEMA_VERSION,
                'sqlite_runtime': sqlite3.sqlite_version, 'revision': payload['updated_at'],
                'file_count': len(payload['files']), 'directory_count': len(payload['directories']),
                'files_digest': _records_digest(payload['files'], 'file_id'),
                'directories_digest': _records_digest(payload['directories'], 'id'),
                'content_included': False}
            _validate_index(InventoryIndex(staging), manifest)
            with (staging / INDEX_FILE).open('rb') as handle:
                manifest['database_sha256'] = hashlib.file_digest(handle, 'sha256').hexdigest()
                os.fsync(handle.fileno())
            _write_json(staging / 'manifest.json', manifest)
            staging.replace(destination)
            for directory in (backups, data_root):
                descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return {'status': 'backed_up', 'path': str(destination.relative_to(data_root)), **manifest}


def rollback_inventory(data_root: Path) -> dict:
    """Reverse-export current metadata under the same mutation fence, including new writes."""
    with storage_mutation_lock(data_root):
        marker = json.loads((data_root / 'inventory-store.json').read_text())
        if marker.get('adapter') == 'json':
            # A retry must never overwrite JSON writes accepted after reverse cutover.
            _finish_retirement(data_root, marker)
            return {'status': 'rolled_back', **marker}
        index = InventoryIndex(data_root)
        with index.transaction() as connection:
            if connection.execute('SELECT 1 FROM operations LIMIT 1').fetchone():
                raise ValueError('Recover pending Storage mutations before rollback.')
        payload = export_inventory(index)
        digest = _digest(payload)
        backup_id = 'inventory-' + uuid4().hex
        backup_root = _candidate(data_root, backup_id)
        backup_root.mkdir(parents=True)
        index.backup(backup_root / INDEX_FILE)
        _write_json(backup_root / 'export.json', payload)
        if _digest(json.loads((backup_root / 'export.json').read_text())) != digest:
            raise ValueError('Storage rollback export validation failed.')
        _write_json(data_root / 'files.json', payload)
        marker = {'adapter': 'json', 'schema_version': '1',
            'migration_id': backup_id, 'export_digest': digest, 'retire_to': backup_id}
        _write_json(data_root / 'inventory-store.json', marker)
        # All app readers/writers hold this fence. Retire a checkpointed database
        # with no live WAL sidecars before a subsequent forward migration.
        _finish_retirement(data_root, marker)
        return {'status': 'rolled_back', 'adapter': 'json', 'migration_id': backup_id,
            'file_count': len(payload['files']), 'directory_count': len(payload['directories']), 'export_digest': digest}


def _finish_retirement(data_root: Path, marker: dict) -> None:
    """Retry a crash after the reverse marker without re-exporting stale metadata."""
    if marker.get('adapter') != 'json' or not marker.get('retire_to'):
        return
    source = data_root / INDEX_FILE
    if not source.exists():
        return
    destination = _candidate(data_root, marker['retire_to']) / 'retired.sqlite'
    with InventoryIndex(data_root).connect(write=True) as connection:
        if connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
            raise RuntimeError('Storage retirement still has active database readers.')
        if connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
            raise RuntimeError('Storage retirement could not checkpoint the database.')
    source.replace(destination)
