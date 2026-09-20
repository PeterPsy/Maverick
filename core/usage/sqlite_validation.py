"""Explicit validation of derived Usage SQLite counters and stream cursors."""

from core.usage.sqlite_schema import TOKEN_FIELDS


def validate_projection_tables(connection) -> None:
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
        (SELECT 1 FROM samples o WHERE o.sample_id=s.sample_id AND o.observed_at=s.observed_at
            AND o.workspace_id=s.workspace_id AND o.session_id=s.session_id AND o.provider_id=s.provider_id
            AND o.model_id=s.model_id AND o.source=s.source AND o.semantics='cumulative')
        OR EXISTS (SELECT 1 FROM samples o WHERE o.workspace_id=s.workspace_id AND o.session_id=s.session_id
            AND o.provider_id=s.provider_id AND o.model_id=s.model_id AND o.source=s.source AND o.semantics='cumulative'
            AND (o.observed_at,o.sample_id)>(s.observed_at,s.sample_id))''').fetchone()[0]
    expected_streams = connection.execute("SELECT COUNT(*) FROM (SELECT 1 FROM samples WHERE semantics='cumulative' "
        "GROUP BY workspace_id,session_id,provider_id,model_id,source)").fetchone()[0]
    if bad_streams or connection.execute('SELECT COUNT(*) FROM streams').fetchone()[0] != expected_streams:
        raise RuntimeError('Usage stream cursor validation failed.')
