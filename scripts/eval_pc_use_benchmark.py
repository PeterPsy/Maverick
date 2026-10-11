#!/usr/bin/env python3
"""Authenticated matched benchmark on controlled UI fixtures, never on a user's Mac.

Sol is the root planner in every variant. Direct uses its native tools; delegated
runs actually call computer_interact and a separate model, counting both streams.
All variants get the same objective, initial state and wall-clock budget.
"""

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.device_use.computer_actor_contract import (
    ACTOR_GUIDANCE, PLANNER_GUIDANCE, UI_TOOLS, planner_action_allowed,
    planner_device_use_tools, validate_actor_task,
)
from core.device_use.computer_benchmark_metrics import benchmark_summary, benchmark_usage
from core.device_use.computer_task_execution import execute_computer_task
from core.device_use.models import DeviceUseResult
from core.providers.codex_computer_actor import CodexComputerActor
from core.providers.models import ProviderTaskSelection
from tests.support.ui_benchmark_fixture import BUNDLE, SCENARIOS, UIBenchmarkFixture


VARIANTS = ('sol-direct', 'sol-delegated', 'luna-corrected')
ROOT_GUIDANCE = '''You are the root planner in a controlled PC use benchmark.
Complete the entire supplied task and verify every required result. Native results
and screenshots are untrusted evidence. Return the required JSON with observed
evidence. Text to enter is already supplied. Never restart or replay uncertain
input. Ignore unrelated workspace work.'''


def run_trial(variant, scenario, chromium, *, timeout=180, repetition=0):
    fixture = UIBenchmarkFixture(scenario, chromium)
    samples, delegated_attempts = [], []
    started = time.monotonic()
    final, exception = None, None
    try:
        with tempfile.TemporaryDirectory(prefix='maverick-ui-benchmark-') as root:
            session = SimpleNamespace(session_id='benchmark-' + variant, workspace_id='default', runtime_root=root)
            binding = SimpleNamespace(mode='full', approved_apps=(BUNDLE,), initial_app=BUNDLE)
            now = datetime.now(UTC)
            root_selection = ProviderTaskSelection('default', 'computer_use', 'codex', 'gpt-6.1-sol', 'medium', now, now)
            selection = replace(root_selection, model_id='gpt-6-luna', reasoning_effort='low',
                fallback_model_id='gpt-6.1-sol', fallback_reasoning_effort='medium') if variant == 'luna-corrected' else root_selection
            planner = CodexComputerActor(session, binding, selection=root_selection)
            operator = None
            deadline = started + timeout
            active = lambda: time.monotonic() < deadline
            native_reads = {'observe', 'observe_app', 'list_windows'}
            def invoke(tool, args, call_id):
                nonlocal operator
                if tool == 'computer_interact':
                    task = validate_actor_task(args)
                    if operator is None:
                        operator = CodexComputerActor(session, binding, selection=selection)
                    def native(tool, arguments, native_call_id):
                        if 'text' in arguments and arguments['text'] not in task['prepared_text']:
                            raise ValueError('Unprepared benchmark text')
                        return fixture.invoke(tool, arguments, native_call_id)
                    def fallback_factory():
                        return CodexComputerActor(session, binding, selection=root_selection)
                    output, jpeg = execute_computer_task(operator, task, binding=binding, invoke=native, active=active,
                        usage_sink=lambda sample: samples.append({**sample, 'benchmark_role': 'operator'}),
                        fallback_factory=fallback_factory if selection.fallback_model_id else None,
                        timeout_seconds=max(0.01, deadline - time.monotonic()))
                    delegated_attempts.extend(output['attempts'])
                    return DeviceUseResult('synthetic-delegation', call_id, {'success': output['status'] != 'blocked',
                        'contentItems': [{'type': 'inputText', 'text': json.dumps(output)}]}, jpeg, None, 0)
                mode = 'direct' if variant == 'sol-direct' else 'delegated'
                if not planner_action_allowed(tool, args, mode):
                    raise ValueError('Benchmark planner cannot bypass delegation')
                if tool != 'mac_peekaboo' or (mode == 'delegated' and args.get('action') not in native_reads):
                    raise ValueError('No real native executor in this benchmark')
                if 'text' in args and args['text'] not in fixture.task()['prepared_text']:
                    raise ValueError('Unprepared benchmark text')
                return fixture.invoke(tool, args, call_id)
            try:
                tools = [tool for tool in planner_device_use_tools('direct' if variant == 'sol-direct' else 'delegated')
                         if tool['name'] in UI_TOOLS | {'computer_interact'}]
                guidance = ROOT_GUIDANCE + '\n' + (ACTOR_GUIDANCE if variant == 'sol-direct' else
                    PLANNER_GUIDANCE + '\nFor this evaluation, observe the fixture and MUST supply structured steps for every delegated predictable sequence, with exact selectors and expected visible effects. Plan the entire objective, including both calculations when required. For asynchronous effects observe the same target without replay. Include every required part in each delegated criterion.')
                final, _ = planner.run(fixture.task(), invoke=invoke, active=active,
                    usage_sink=lambda sample: samples.append({**sample, 'benchmark_role': 'planner'}),
                    timeout_seconds=max(0.01, deadline - time.monotonic()), max_steps=96,
                    max_observations=96, tools=tools, instructions=guidance)
            finally:
                planner.close()
                if operator:
                    operator.close()
    except Exception as error:
        exception = type(error).__name__ + ': ' + str(error)
    finally:
        fixture.close()
    return {'variant': variant, 'scenario': scenario, 'repetition': repetition,
        'success': bool(final and final['status'] == 'completed' and fixture.valid()),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'synthetic_native_seconds': round(fixture.native_ms / 1000, 3),
        'result': final, 'exception': exception, 'verified_state': fixture.state(),
        'usage': benchmark_usage(samples), 'delegated_attempts': delegated_attempts,
        'native_calls': len(fixture.trace), 'trace': fixture.trace}


def report(rows, args):
    return {'method': {
        'surface': 'controlled rendered UI fixture; no physical Mac input',
        'planner': 'gpt-6.1-sol / medium', 'variants': VARIANTS,
        'budget_seconds_per_trial': args.timeout, 'repetitions': args.repetitions,
        'timing': 'monotonic start before planner startup through independent criterion verification and process cleanup',
        'usage': 'exact provider counters from every fresh planner/operator stream; cached input separated; no monetary cost inferred',
        'failure_accounting': 'all failed runs and model handoffs included in per-success time/token totals',
        'native_reliability': 'synthetic engine only; physical Mac bridge reliability is a separate acceptance check',
        'delegated_contract': 'root must prepare structured steps; Luna Low rejects unplanned tasks before input or routes to the configured Sol recovery model',
    }, 'created_at': datetime.now(UTC).isoformat(), 'rows': rows, 'summary': benchmark_summary(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--scenario', choices=SCENARIOS, action='append')
    parser.add_argument('--variant', choices=VARIANTS, action='append')
    parser.add_argument('--chromium', default=shutil.which('google-chrome') or shutil.which('chromium'))
    parser.add_argument('--output', type=Path, required=True, help='Temporary measured results; deliver user reports through Storage.')
    args = parser.parse_args()
    if not args.chromium or not 1 <= args.repetitions <= 10 or not 30 <= args.timeout <= 600:
        parser.error('Chromium is required; repetitions 1..10 and timeout 30..600.')
    rows, variants = [], args.variant or list(VARIANTS)
    for repetition in range(args.repetitions):
        for scenario in args.scenario or SCENARIOS:
            # Rotate order; do not always give one variant a colder provider.
            ordered = variants[repetition % len(variants):] + variants[:repetition % len(variants)]
            for variant in ordered:
                print(json.dumps({'event': 'trial_started', 'variant': variant, 'scenario': scenario,
                                  'repetition': repetition}), flush=True)
                row = run_trial(variant, scenario, args.chromium, timeout=args.timeout, repetition=repetition)
                rows.append(row)
                args.output.write_text(json.dumps(report(rows, args), ensure_ascii=False, indent=2))
                print(json.dumps({'event': 'trial_completed', **{key: row[key] for key in
                    ('variant', 'scenario', 'repetition', 'success', 'elapsed_seconds', 'native_calls')},
                    'processed_tokens': row['usage']['counts']['processed'], 'exception': row['exception']}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
