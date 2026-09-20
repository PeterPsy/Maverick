"""Deterministic fake datasets for the server/PWA performance checkpoints."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from core.shared.json_file_collection import JsonFileCollection
from core.usage.models import UsageSampleRecord
from core.usage.store import UsageCollections, UsageDocumentStore

EPOCH = datetime(2026, 9, 1, tzinfo=UTC)


def storage_files(root: Path, count: int, *, shape: str) -> tuple[Path, Path, Path]:
    uploaded, generated, data = root / 'storage/uploaded', root / 'storage/generated', root / 'data/storage'
    for path in (uploaded, generated, data):
        path.mkdir(parents=True)
    for index in range(count):
        parent = generated if shape == 'flat' else generated / f'project-{index % 20}' / f'year-{index % 5}' / 'reports'
        if shape == 'deep':
            parent = parent.joinpath(*(f'level-{depth}' for depth in range(8)))
        parent.mkdir(parents=True, exist_ok=True)
        (parent / f'report-{index:06d}.md').write_text(f'# Fixture {index}\n' + 'Bounded synthetic document.\n' * 10)
    (generated / 'empty').mkdir()
    return uploaded, generated, data


def usage_sample(index: int) -> UsageSampleRecord:
    return UsageSampleRecord(
        sample_id=f'sample-{index:08d}', workspace_id='fixture',
        root_session_id=f'root-{index % 4}', session_id=f'root-{index % 4}',
        turn_id=f'turn-{index}', provider_id=('codex', 'openrouter')[index % 2],
        model_id=f'model-{index % 3}', source='performance-fixture', semantics='incremental',
        token_accuracy='exact', context_accuracy='exact', input_tokens=100,
        cached_input_tokens=20, cache_write_input_tokens=0, output_tokens=50,
        reasoning_output_tokens=5, total_tokens=175, reported_input_tokens=120,
        reported_cached_input_tokens=20, reported_cache_write_input_tokens=0,
        reported_output_tokens=55, reported_reasoning_output_tokens=5, reported_total_tokens=175,
        context_tokens=175, context_window_tokens=100000, estimated_cost_microusd=None,
        observed_at=EPOCH + timedelta(seconds=index),
    )


def usage_document_state(root: Path, count: int):
    samples = JsonFileCollection(root / 'usage_samples.json')
    samples.replace_all([asdict(usage_sample(index)) for index in range(count)])
    store = UsageDocumentStore(UsageCollections(
        samples=samples, buckets=JsonFileCollection(root / 'usage_buckets.json'),
        quota_snapshots=JsonFileCollection(root / 'usage_quotas.json'),
    ))
    sessions = {f'root-{index}': SimpleNamespace(
        session_id=f'root-{index}', workspace_id='fixture', creator_runtime_session_id=None,
        execution_binding=None, hosted_provider_id=None, hosted_model_id=None, provider_id='codex',
    ) for index in range(4)}
    return SimpleNamespace(usage_store=store, runtime_store=SimpleNamespace(get_session=sessions.__getitem__), provider_registry=None)
