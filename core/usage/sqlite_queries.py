"""Read-only usage summaries and bounded charts from transactional projections."""

from datetime import UTC, datetime, timedelta
import json

from core.usage.models import ChatUsageSummary, TokenUsageBreakdown
from core.usage.sqlite_schema import TOKEN_FIELDS, decode_sample, timestamp
from core.usage.timeseries import MAX_DAILY_PERIODS, MAX_HOURLY_PERIODS, usage_bucket_start


def _tokens(rows) -> TokenUsageBreakdown:
    return TokenUsageBreakdown(**{field: sum(row[field] for row in rows) for field in TOKEN_FIELDS})


def _totals(rows) -> dict:
    return {**{field: sum(row[field] for row in rows) for field in TOKEN_FIELDS},
        'estimated_cost_microusd': sum(row['cost_sum'] for row in rows) if sum(row['cost_count'] for row in rows) else None}


def chat_summary(connection, *, workspace_id: str, root_session_id: str, direct_session_ids: set[str]) -> ChatUsageSummary:
    rows = list(connection.execute('SELECT * FROM session_totals WHERE workspace_id=? AND root_session_id=? AND sample_count>0',
        (workspace_id, root_session_id)))
    direct = [row for row in rows if row['session_id'] in direct_session_ids]
    delegated = [row for row in rows if row['session_id'] not in direct_session_ids]
    context = connection.execute('''SELECT document FROM samples WHERE workspace_id=? AND root_session_id=?
        AND context_tokens IS NOT NULL AND session_id IN (SELECT value FROM json_each(?))
        ORDER BY observed_at DESC,sample_id DESC LIMIT 1''',
        (workspace_id, root_session_id, json.dumps(sorted(direct_session_ids)))).fetchone()
    latest = decode_sample(context[0]) if context else None
    context_tokens = latest.context_tokens if latest else None
    window = latest.context_window_tokens if latest else None
    estimated = sum(row['estimated_count'] for row in rows)
    unavailable = sum(row['unavailable_count'] for row in rows)
    return ChatUsageSummary(workspace_id=workspace_id, root_session_id=root_session_id,
        tokens=_tokens(rows), direct_tokens=_tokens(direct), delegated_tokens=_tokens(delegated),
        context_tokens=context_tokens, context_window_tokens=window,
        context_used_percent=round(min(100.0, max(0.0, context_tokens / window * 100.0)), 1) if context_tokens is not None and window else None,
        token_accuracy='estimated' if estimated else ('unavailable' if unavailable or not rows else 'exact'),
        context_accuracy=latest.context_accuracy if latest else 'unavailable',
        provider_ids=tuple(sorted({row['provider_id'] for row in rows})),
        model_ids=tuple(sorted({row['model_id'] for row in rows if row['model_id']})),
        estimated_cost_microusd=_totals(rows)['estimated_cost_microusd'],
        sample_count=sum(row['sample_count'] for row in rows),
        coverage_since=datetime.fromisoformat(min(row['first_at'] for row in rows)) if rows else None,
        updated_at=datetime.fromisoformat(max(row['last_at'] for row in rows)) if rows else None)


def timeseries(connection, *, workspace_id: str, resolution: str, periods: int,
               provider_id: str | None = None, model_id: str | None = None,
               now: datetime | None = None) -> dict[str, object]:
    bounded = max(1, min(int(periods), MAX_HOURLY_PERIODS if resolution == 'hour' else MAX_DAILY_PERIODS))
    generated = now or datetime.now(tz=UTC)
    current = usage_bucket_start(generated, resolution)
    step = timedelta(hours=1) if resolution == 'hour' else timedelta(days=1)
    start, end = current - step * (bounded - 1), current + step
    rows = list(connection.execute('''SELECT * FROM buckets WHERE workspace_id=? AND resolution=?
        AND bucket_start>=? AND bucket_start<? AND sample_count>0 ORDER BY bucket_start,provider_id,model_id''',
        (workspace_id, resolution, timestamp(start), timestamp(end))))
    matching = [row for row in rows if (provider_id is None or row['provider_id'] == provider_id)
        and (model_id is None or row['model_id'] == model_id)]
    grouped = {}
    models = {}
    for row in matching:
        grouped.setdefault(row['bucket_start'], []).append(row)
    for row in rows:
        models.setdefault(row['provider_id'], set())
        if row['model_id']:
            models[row['provider_id']].add(row['model_id'])
    items = []
    for index in range(bounded):
        bucket_start = start + step * index
        values = grouped.get(timestamp(bucket_start), [])
        items.append({'bucket_start': bucket_start, 'bucket_end': bucket_start + step,
            **_totals(values), 'sample_count': sum(row['sample_count'] for row in values)})
    return {'workspace_id': workspace_id, 'resolution': resolution, 'periods': bounded,
        'provider_id': provider_id, 'model_id': model_id, 'timezone': 'UTC',
        'range_start': start, 'range_end': end,
        'coverage_since': datetime.fromisoformat(min(row['first_at'] for row in matching)) if matching else None,
        'generated_at': generated, 'facets': {'providers': [
            {'provider_id': provider, 'model_ids': sorted(values)} for provider, values in sorted(models.items())]},
        'items': items, 'totals': _totals(matching)}
