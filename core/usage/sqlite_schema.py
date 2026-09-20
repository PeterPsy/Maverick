"""Usage-owned SQLite schema and record encoding; no control-plane collection coupling."""

from dataclasses import asdict
from datetime import UTC, datetime
import json

from core.usage.models import UsageSampleRecord

SCHEMA_VERSION = 1
TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
                'output_tokens', 'reasoning_output_tokens', 'total_tokens')
TOKEN_COLUMNS = ','.join(f'{field} INTEGER NOT NULL' for field in TOKEN_FIELDS)
ROLLUP_COLUMNS = TOKEN_COLUMNS + ''',cost_sum INTEGER NOT NULL,cost_count INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,estimated_count INTEGER NOT NULL,unavailable_count INTEGER NOT NULL,
    first_at TEXT NOT NULL,last_at TEXT NOT NULL'''
SCHEMA = f'''
CREATE TABLE samples (
    sample_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, root_session_id TEXT NOT NULL,
    session_id TEXT NOT NULL, provider_id TEXT NOT NULL, model_id TEXT NOT NULL,
    source TEXT NOT NULL, semantics TEXT NOT NULL, observed_at TEXT NOT NULL,
    {TOKEN_COLUMNS}, estimated_cost_microusd INTEGER, context_tokens INTEGER,
    raw_payload TEXT, document TEXT NOT NULL
);
CREATE INDEX stream_samples ON samples(workspace_id,session_id,provider_id,model_id,source,semantics,observed_at,sample_id);
CREATE INDEX root_samples ON samples(workspace_id,root_session_id,observed_at,sample_id);
CREATE INDEX session_samples ON samples(session_id,observed_at,sample_id);
CREATE INDEX bucket_samples ON samples(workspace_id,provider_id,model_id,observed_at,sample_id);
CREATE INDEX context_samples ON samples(workspace_id,root_session_id,observed_at DESC,sample_id DESC)
    WHERE context_tokens IS NOT NULL;
CREATE TABLE streams (
    workspace_id TEXT NOT NULL,session_id TEXT NOT NULL,provider_id TEXT NOT NULL,model_id TEXT NOT NULL,source TEXT NOT NULL,
    observed_at TEXT NOT NULL,sample_id TEXT NOT NULL,
    PRIMARY KEY(workspace_id,session_id,provider_id,model_id,source)
) WITHOUT ROWID;
CREATE TABLE session_totals (
    workspace_id TEXT NOT NULL,root_session_id TEXT NOT NULL,session_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,model_id TEXT NOT NULL,{ROLLUP_COLUMNS},
    PRIMARY KEY(workspace_id,root_session_id,session_id,provider_id,model_id)
) WITHOUT ROWID;
CREATE INDEX totals_session ON session_totals(session_id);
CREATE TABLE buckets (
    workspace_id TEXT NOT NULL,resolution TEXT NOT NULL,bucket_start TEXT NOT NULL,
    provider_id TEXT NOT NULL,model_id TEXT NOT NULL,{ROLLUP_COLUMNS},
    PRIMARY KEY(workspace_id,resolution,bucket_start,provider_id,model_id)
) WITHOUT ROWID;
CREATE TABLE quota_snapshots (
    snapshot_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,observed_at TEXT NOT NULL,document TEXT NOT NULL
);
CREATE INDEX quota_workspace ON quota_snapshots(workspace_id,observed_at,snapshot_id);
'''


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec='microseconds')


def encode_record(record) -> str:
    return json.dumps(asdict(record), ensure_ascii=False, separators=(',', ':'),
        default=lambda value: timestamp(value) if isinstance(value, datetime) else value)


def decode_sample(document: str) -> UsageSampleRecord:
    value = json.loads(document)
    value['observed_at'] = datetime.fromisoformat(value['observed_at'])
    return UsageSampleRecord(**value)
