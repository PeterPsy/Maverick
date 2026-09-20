"""Explicit Usage export and migration validation; never used by ordinary reads."""

from dataclasses import asdict
from datetime import datetime
import hashlib
import json

from core.usage.canonical import canonical_usage_samples
from core.usage.models import ProviderQuotaSnapshotRecord, UsageSampleRecord
from core.usage.sqlite_schema import TOKEN_FIELDS, decode_sample
from core.usage.timeseries import _bucket_record, usage_bucket_start


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def document_snapshot(collections) -> dict:
    return {name: sorted(list(getattr(collections, name).find({})), key=lambda record: record[identity])
        for name, identity in (('samples', 'sample_id'), ('buckets', 'bucket_id'), ('quota_snapshots', 'snapshot_id'))}


def samples_from_snapshot(snapshot: dict) -> list[UsageSampleRecord]:
    samples = [UsageSampleRecord(**decode_dates(value)) for value in snapshot['samples']]
    return canonical_usage_samples(sorted(samples, key=lambda sample: (sample.observed_at, sample.sample_id)))


def decode_dates(document: dict) -> dict:
    return {key: datetime.fromisoformat(value) if key in {'observed_at', 'bucket_start', 'bucket_end', 'updated_at'}
        and isinstance(value, str) else value for key, value in document.items()}


def import_snapshot(store, snapshot: dict) -> None:
    store.import_samples(samples_from_snapshot(snapshot))
    for value in snapshot['quota_snapshots']:
        store.save_quota_snapshot_if_absent(ProviderQuotaSnapshotRecord(**decode_dates(value)))


def sqlite_snapshot(store) -> dict:
    with store.transaction() as connection:
        samples = [decode_sample(row[0]) for row in connection.execute('SELECT document FROM samples ORDER BY sample_id')]
        quotas = [decode_dates(json.loads(row[0])) for row in connection.execute('SELECT document FROM quota_snapshots ORDER BY snapshot_id')]
    grouped = {}
    for sample in samples:
        for resolution in ('hour', 'day'):
            key = (sample.workspace_id, resolution, usage_bucket_start(sample.observed_at, resolution), sample.provider_id, sample.model_id)
            grouped.setdefault(key, []).append(sample)
    buckets = [asdict(_bucket_record(values, resolution=key[1], bucket_start=key[2])) for key, values in grouped.items()]
    return {'samples': [asdict(sample) for sample in samples], 'quota_snapshots': quotas,
            'buckets': sorted(buckets, key=lambda value: value['bucket_id'])}


def canonical_digest(snapshot: dict) -> str:
    samples = sorted((asdict(sample) for sample in samples_from_snapshot(snapshot)), key=lambda sample: sample['sample_id'])
    quotas = sorted((decode_dates(value) for value in snapshot['quota_snapshots']), key=lambda value: value['snapshot_id'])
    return digest({'samples': samples, 'quota_snapshots': quotas})


def validate_database(store, *, expected_digest: str | None = None) -> dict:
    snapshot = sqlite_snapshot(store)
    actual = canonical_digest(snapshot)
    with store.transaction() as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Usage SQLite integrity validation failed.')
        # Check materialized counters against source observations, including zero costs and accuracy.
        counters = (*TOKEN_FIELDS, 'cost_sum', 'cost_count', 'sample_count', 'estimated_count', 'unavailable_count')
        expressions = (*TOKEN_FIELDS, 'COALESCE(estimated_cost_microusd,0)', 'estimated_cost_microusd IS NOT NULL', '1',
            "json_extract(document,'$.token_accuracy')='estimated'", "json_extract(document,'$.token_accuracy')='unavailable'")
        aggregates = ','.join(f'SUM({field})' for field in expressions) + ',MIN(observed_at),MAX(observed_at)'
        projection_values = ','.join((*counters, 'first_at', 'last_at'))
        for table, keys, projection_keys, clause in (
            ('session_totals', 'workspace_id,root_session_id,session_id,provider_id,model_id',
                'workspace_id,root_session_id,session_id,provider_id,model_id', ''),
            ('buckets', "workspace_id,substr(observed_at,1,13)||':00:00.000000+00:00',provider_id,model_id",
                'workspace_id,bucket_start,provider_id,model_id', "WHERE resolution='hour'"),
            ('buckets', "workspace_id,substr(observed_at,1,10)||'T00:00:00.000000+00:00',provider_id,model_id",
                'workspace_id,bucket_start,provider_id,model_id', "WHERE resolution='day'"),
        ):
            expected_query = f'SELECT {keys},{aggregates} FROM samples GROUP BY {keys}'
            actual_query = f'SELECT {projection_keys},{projection_values} FROM {table} {clause}'
            if connection.execute(f'{expected_query} EXCEPT {actual_query} LIMIT 1').fetchone() or connection.execute(
                    f'{actual_query} EXCEPT {expected_query} LIMIT 1').fetchone():
                raise RuntimeError('Usage projection validation failed.')
        bad_streams = connection.execute('''SELECT COUNT(*) FROM streams s WHERE NOT EXISTS
            (SELECT 1 FROM samples o WHERE o.sample_id=s.sample_id AND o.observed_at=s.observed_at)
            OR EXISTS (SELECT 1 FROM samples o WHERE o.workspace_id=s.workspace_id AND o.session_id=s.session_id
                AND o.provider_id=s.provider_id AND o.model_id=s.model_id AND o.source=s.source AND o.semantics='cumulative'
                AND (o.observed_at,o.sample_id)>(s.observed_at,s.sample_id))''').fetchone()[0]
        expected_streams = connection.execute("SELECT COUNT(*) FROM (SELECT 1 FROM samples WHERE semantics='cumulative' "
            "GROUP BY workspace_id,session_id,provider_id,model_id,source)").fetchone()[0]
        if bad_streams or connection.execute('SELECT COUNT(*) FROM streams').fetchone()[0] != expected_streams:
            raise RuntimeError('Usage stream cursor validation failed.')
    if expected_digest is not None and actual != expected_digest:
        raise RuntimeError('Usage sample or quota identities changed during migration.')
    return {'digest': actual, 'counts': {name: len(values) for name, values in snapshot.items()}, 'integrity': 'ok'}


def restore_document_snapshot(collections, snapshot: dict) -> None:
    for name, values in snapshot.items():
        getattr(collections, name).replace_all([decode_dates(value) for value in values])
    if canonical_digest(document_snapshot(collections)) != canonical_digest(snapshot):
        raise RuntimeError('Usage reverse export validation failed.')
