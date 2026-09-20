"""Transactional additions and compensations to the two usage projection families."""

from core.usage.models import UsageSampleRecord
from core.usage.sqlite_schema import TOKEN_FIELDS, timestamp
from core.usage.timeseries import usage_bucket_start

COUNTERS = (*TOKEN_FIELDS, 'cost_sum', 'cost_count', 'sample_count', 'estimated_count', 'unavailable_count')


def adjust_projections(connection, sample: UsageSampleRecord, direction: int) -> None:
    values = [direction * getattr(sample, field) for field in TOKEN_FIELDS]
    values.extend((direction * (sample.estimated_cost_microusd or 0),
        direction * int(sample.estimated_cost_microusd is not None), direction,
        direction * int(sample.token_accuracy == 'estimated'), direction * int(sample.token_accuracy == 'unavailable')))
    observed = timestamp(sample.observed_at)
    _add(connection, 'session_totals', ('workspace_id', 'root_session_id', 'session_id', 'provider_id', 'model_id'),
        (sample.workspace_id, sample.root_session_id, sample.session_id, sample.provider_id, sample.model_id or ''), values, observed)
    for resolution in ('hour', 'day'):
        _add(connection, 'buckets', ('workspace_id', 'resolution', 'bucket_start', 'provider_id', 'model_id'),
            (sample.workspace_id, resolution, timestamp(usage_bucket_start(sample.observed_at, resolution)),
             sample.provider_id, sample.model_id or ''), values, observed)


def _add(connection, table: str, keys: tuple, identity: tuple, values: list, observed: str):
    columns = (*keys, *COUNTERS, 'first_at', 'last_at')
    updates = ','.join(f'{name}={name}+excluded.{name}' for name in COUNTERS)
    connection.execute(f'''INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})
        ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates},
        first_at=MIN(first_at,excluded.first_at),last_at=MAX(last_at,excluded.last_at)''',
        [*identity, *values, observed, observed])
