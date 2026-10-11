"""Matched-task metrics including failures, cache and internal model streams."""

import statistics


def benchmark_usage(samples):
    # Every benchmark context starts a fresh thread. Keep one final cumulative
    # snapshot per stream, rather than summing repeated tokenUsage notifications.
    streams = {}
    for sample in samples:
        key = (sample['source'], sample['model_id'], sample.get('benchmark_role', 'operator'))
        previous = streams.get(key)
        if previous is None or sample['total_tokens'] >= previous['total_tokens']:
            streams[key] = sample
    counts = {key: 0 for key in ('uncached_input', 'cached_input', 'cache_write_input', 'output', 'reasoning_output', 'processed')}
    by_model = {}
    for sample in streams.values():
        cached, written = sample.get('cached_input_tokens', 0), sample.get('cache_write_input_tokens', 0)
        reasoning = sample.get('reasoning_output_tokens', 0)
        current = {'uncached_input': max(0, sample['input_tokens'] - cached - written),
            'cached_input': cached, 'cache_write_input': written,
            'output': max(0, sample['output_tokens'] - reasoning), 'reasoning_output': reasoning,
            'processed': sample['total_tokens']}
        for key, value in current.items():
            counts[key] += value
        model = by_model.setdefault(sample['model_id'], {key: 0 for key in counts})
        for key, value in current.items():
            model[key] += value
    return {'counts': counts, 'by_model': by_model, 'stream_count': len(streams),
            'accuracy': 'exact_provider_counters', 'estimated_cost_usd': None}


def benchmark_summary(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row['variant'], row['scenario']), []).append(row)
    result = []
    for (variant, scenario), records in sorted(groups.items()):
        passed = [row for row in records if row['success']]
        total_time = sum(row['elapsed_seconds'] for row in records)
        tokens = sum(row['usage']['counts']['processed'] for row in records)
        result.append({'variant': variant, 'scenario': scenario, 'runs': len(records), 'successes': len(passed),
            'median_success_seconds': statistics.median(row['elapsed_seconds'] for row in passed) if passed else None,
            'all_attempt_seconds': total_time, 'seconds_per_success_including_failures': total_time / len(passed) if passed else None,
            'all_attempt_tokens': tokens, 'tokens_per_success_including_failures': tokens / len(passed) if passed else None})
    return result
