"""Durable atomic usage observations and projections in the Usage domain's SQLite store."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3

from core.shared.sqlite_runtime import require_safe_wal_runtime
from core.usage.handoff import usage_fence
from core.usage.models import ProviderQuotaSnapshotRecord, UsageSampleRecord
from core.usage.normalization import cumulative_sample_with_previous, stored_usage_observation
from core.usage.sqlite_projections import adjust_projections
from core.usage.sqlite_schema import SCHEMA, SCHEMA_VERSION, TOKEN_FIELDS, decode_sample, encode_record, timestamp
from core.usage.store import SampleBuilder
from core.usage.timeseries import usage_bucket_start


class UsageSqliteHistory:
    def __init__(self, connection):
        self.connection = connection

    def previous_cumulative_sample(self, *, workspace_id: str, session_id: str, provider_id: str,
        model_id: str | None, source: str, before: datetime, sample_id: str) -> UsageSampleRecord | None:
        row = self.connection.execute('''SELECT document FROM samples WHERE workspace_id=? AND session_id=? AND provider_id=?
            AND model_id=? AND source=? AND semantics='cumulative' AND (observed_at,sample_id)<(?,?)
            ORDER BY observed_at DESC,sample_id DESC LIMIT 1''',
            (workspace_id, session_id, provider_id, model_id or '', source, timestamp(before), sample_id)).fetchone()
        return decode_sample(row[0]) if row else None


class UsageSqliteStore:
    def __init__(self, path: Path, *, handoff_root: Path | None = None):
        self.path = path.absolute()
        self.handoff_root = handoff_root

    def initialize(self) -> None:
        """Only explicit installation/migration creates the authoritative database."""
        require_safe_wal_runtime()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
        os.close(descriptor)
        with self.connection(write=True, check_schema=False) as connection:
            if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
                raise RuntimeError('Usage SQLite requires a local WAL-capable filesystem.')
            connection.executescript(f'BEGIN IMMEDIATE;\n{SCHEMA}\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;')

    @contextmanager
    def connection(self, *, write: bool = False, check_schema: bool = True):
        require_safe_wal_runtime()
        connection = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'),
            uri=True, timeout=1.0, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            if check_schema and connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise RuntimeError('Unsupported Usage SQLite schema; explicit migration required.')
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, write: bool = False):
        with (usage_fence(self.handoff_root, expected='sqlite') if self.handoff_root else nullcontext()), self.connection(write=write) as connection:
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def previous_cumulative_sample(self, **filters) -> UsageSampleRecord | None:
        with self.transaction() as connection:
            return UsageSqliteHistory(connection).previous_cumulative_sample(**filters)

    def ingest_observation(self, builder: SampleBuilder, *, payload: dict) -> tuple[UsageSampleRecord, bool] | None:
        with self.transaction(write=True) as connection:
            history = UsageSqliteHistory(connection)
            sample = builder(history)
            if sample is None:
                return None
            existing = connection.execute('SELECT document FROM samples WHERE sample_id=?', (sample.sample_id,)).fetchone()
            if existing:
                return decode_sample(existing[0]), False
            previous = history.previous_cumulative_sample(workspace_id=sample.workspace_id, session_id=sample.session_id,
                provider_id=sample.provider_id, model_id=sample.model_id, source=sample.source,
                before=sample.observed_at, sample_id=sample.sample_id) if sample.semantics == 'cumulative' else None
            sample = cumulative_sample_with_previous(sample, previous, payload)
            self._put_sample(connection, sample, payload)
            adjust_projections(connection, sample, 1)
            if sample.semantics == 'cumulative':
                successor = connection.execute('''SELECT document,raw_payload FROM samples WHERE workspace_id=? AND session_id=?
                    AND provider_id=? AND model_id=? AND source=? AND semantics='cumulative'
                    AND (observed_at,sample_id)>(?,?) ORDER BY observed_at,sample_id LIMIT 1''',
                    (sample.workspace_id, sample.session_id, sample.provider_id, sample.model_id or '', sample.source,
                     timestamp(sample.observed_at), sample.sample_id)).fetchone()
                if successor:
                    old = decode_sample(successor['document'])
                    raw = json.loads(successor['raw_payload']) if successor['raw_payload'] else None
                    corrected = cumulative_sample_with_previous(old, sample, raw)
                    if corrected != old:
                        adjust_projections(connection, old, -1)
                        self._put_sample(connection, corrected, raw)
                        adjust_projections(connection, corrected, 1)
                self._advance_stream(connection, sample)
            return sample, True

    @staticmethod
    def _put_sample(connection, sample: UsageSampleRecord, payload: dict | None):
        values = [sample.sample_id, sample.workspace_id, sample.root_session_id, sample.session_id,
            sample.provider_id, sample.model_id or '', sample.source, sample.semantics, timestamp(sample.observed_at),
            *(getattr(sample, name) for name in TOKEN_FIELDS), sample.estimated_cost_microusd, sample.context_tokens,
            json.dumps(stored_usage_observation(payload), separators=(',', ':')) if payload is not None else None, encode_record(sample)]
        connection.execute(f'''INSERT INTO samples VALUES ({','.join('?' for _ in values)})
            ON CONFLICT(sample_id) DO UPDATE SET {','.join(f'{name}=excluded.{name}' for name in TOKEN_FIELDS)},
            estimated_cost_microusd=excluded.estimated_cost_microusd,document=excluded.document,raw_payload=excluded.raw_payload''', values)

    @staticmethod
    def _advance_stream(connection, sample: UsageSampleRecord):
        connection.execute('''INSERT INTO streams VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(workspace_id,session_id,provider_id,model_id,source) DO UPDATE SET
            observed_at=excluded.observed_at,sample_id=excluded.sample_id
            WHERE (observed_at,sample_id)<(excluded.observed_at,excluded.sample_id)''',
            (sample.workspace_id, sample.session_id, sample.provider_id, sample.model_id or '', sample.source,
             timestamp(sample.observed_at), sample.sample_id))

    def import_samples(self, samples) -> None:
        """Migration-only bulk import of already canonical source observations."""
        with self.transaction(write=True) as connection:
            for sample in samples:
                if connection.execute('SELECT 1 FROM samples WHERE sample_id=?', (sample.sample_id,)).fetchone():
                    raise ValueError('Duplicate usage identity in the migration source.')
                self._put_sample(connection, sample, None)
                adjust_projections(connection, sample, 1)
                if sample.semantics == 'cumulative':
                    self._advance_stream(connection, sample)

    def list_samples(self, *, workspace_id: str | None = None, root_session_id: str | None = None,
                     session_id: str | None = None) -> list[UsageSampleRecord]:
        where = {key: value for key, value in (('workspace_id', workspace_id), ('root_session_id', root_session_id),
            ('session_id', session_id)) if value is not None}
        with self.transaction() as connection:
            return [decode_sample(row[0]) for row in connection.execute(
                'SELECT document FROM samples' + (' WHERE ' + ' AND '.join(f'{key}=?' for key in where) if where else '')
                + ' ORDER BY observed_at,sample_id', list(where.values()))]

    def chat_summary(self, *, workspace_id: str, root_session_id: str, direct_session_ids: set[str]):
        from core.usage.sqlite_queries import chat_summary
        with self.transaction() as connection:
            return chat_summary(connection, workspace_id=workspace_id, root_session_id=root_session_id,
                direct_session_ids=direct_session_ids)

    def timeseries(self, **filters) -> dict[str, object]:
        from core.usage.sqlite_queries import timeseries
        with self.transaction() as connection:
            return timeseries(connection, **filters)

    def save_quota_snapshot_if_absent(self, record: ProviderQuotaSnapshotRecord) -> tuple[ProviderQuotaSnapshotRecord, bool]:
        with self.transaction(write=True) as connection:
            inserted = connection.execute('INSERT OR IGNORE INTO quota_snapshots VALUES (?,?,?,?)',
                (record.snapshot_id, record.workspace_id, timestamp(record.observed_at), encode_record(record))).rowcount > 0
            row = connection.execute('SELECT document FROM quota_snapshots WHERE snapshot_id=?', (record.snapshot_id,)).fetchone()
        value = json.loads(row[0])
        value['observed_at'] = datetime.fromisoformat(value['observed_at'])
        return ProviderQuotaSnapshotRecord(**value), inserted

    def list_quota_snapshots(self, *, workspace_id: str) -> list[ProviderQuotaSnapshotRecord]:
        with self.transaction() as connection:
            values = [json.loads(row[0]) for row in connection.execute(
                'SELECT document FROM quota_snapshots WHERE workspace_id=? ORDER BY observed_at,snapshot_id', (workspace_id,))]
        return [ProviderQuotaSnapshotRecord(**{**value, 'observed_at': datetime.fromisoformat(value['observed_at'])}) for value in values]

    def delete_session(self, session_id: str) -> int:
        return self.delete_sessions([session_id]).get(session_id, 0)

    def delete_sessions(self, session_ids: list[str]) -> dict[str, int]:
        deleted = dict.fromkeys(session_ids, 0)
        if not deleted:
            return deleted
        affected = set()
        ids = json.dumps(list(deleted))
        with self.transaction(write=True) as connection:
            for row in connection.execute('SELECT document FROM samples WHERE session_id IN (SELECT value FROM json_each(?))', (ids,)):
                sample = decode_sample(row[0])
                deleted[sample.session_id] += 1
                adjust_projections(connection, sample, -1)
                for resolution in ('hour', 'day'):
                    affected.add((sample.workspace_id, resolution, usage_bucket_start(sample.observed_at, resolution), sample.provider_id, sample.model_id or ''))
            connection.execute('DELETE FROM samples WHERE session_id IN (SELECT value FROM json_each(?))', (ids,))
            connection.execute('DELETE FROM streams WHERE session_id IN (SELECT value FROM json_each(?))', (ids,))
            connection.execute('DELETE FROM session_totals WHERE sample_count=0')
            connection.execute('DELETE FROM buckets WHERE sample_count=0')
            for workspace, resolution, start, provider, model in affected:
                end = start + (timedelta(hours=1) if resolution == 'hour' else timedelta(days=1))
                bounds = connection.execute('''SELECT MIN(observed_at),MAX(observed_at) FROM samples
                    WHERE workspace_id=? AND provider_id=? AND model_id=? AND observed_at>=? AND observed_at<?''',
                    (workspace, provider, model, timestamp(start), timestamp(end))).fetchone()
                if bounds[0]:
                    connection.execute('''UPDATE buckets SET first_at=?,last_at=? WHERE workspace_id=?
                        AND resolution=? AND bucket_start=? AND provider_id=? AND model_id=?''',
                        (*bounds, workspace, resolution, timestamp(start), provider, model))
        return deleted

    def backup(self, destination: Path) -> None:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
        os.close(descriptor)
        with self.connection() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
