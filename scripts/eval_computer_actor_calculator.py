#!/usr/bin/env python3
"""Opt-in authenticated Codex evaluation; synthetic native callbacks only.

Requires the installed Browser app's Playwright dependency and a local Chromium.
It never calls native Mac tools. Every receipt renumbers targets; input effects
settle on a later read. Exit success requires a completed, correct final display.
"""

import argparse
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.device_use.models import DeviceUseResult
from core.providers.codex_computer_actor import CodexComputerActor


BUNDLE = 'com.example.calculator-fixture'
LABELS = ['Clear', 'PlusMinus', 'Percent', 'Divide', 'Seven', 'Eight', 'Nine', 'Multiply',
          'Four', 'Five', 'Six', 'Subtract', 'One', 'Two', 'Three', 'Add', 'Zero', 'Decimal', 'Equals']
DIGITS = dict(zip(['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'], '0123456789'))


class CalculatorFixture:
    def __init__(self, chromium):
        self.renderer = subprocess.Popen([
            'node', str(ROOT / 'tests/support/computer_actor_calculator_renderer.cjs'),
            str(ROOT / 'apps/browser/node_modules/playwright'), chromium,
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.value, self.left, self.operation, self.fresh = '0', None, None, True
        self.generation, self.pending, self.receipt, self.elements = 0, None, '', {}
        self.trace = []

    def close(self):
        self.renderer.stdin.close()
        try:
            self.renderer.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.renderer.terminate()
            self.renderer.wait(timeout=5)
        self.renderer.stdout.close()
        self.renderer.stderr.close()

    def apply(self, label):
        if label == 'Clear':
            self.value, self.left, self.operation, self.fresh = '0', None, None, True
        elif label in DIGITS:
            self.value = DIGITS[label] if self.fresh or self.value == '0' else self.value + DIGITS[label]
            self.fresh = False
        elif label == 'Multiply':
            self.left, self.operation, self.fresh = int(self.value), 'multiply', True
        elif label == 'Equals' and self.operation == 'multiply':
            self.value, self.fresh, self.operation = str(self.left * int(self.value)), True, None
        else:
            raise ValueError('Unsupported fixture operation: ' + label)

    def result(self, call_id, success=True):
        self.generation += 1
        self.receipt = 'ps1_fixture_' + str(self.generation)
        self.elements = {f'elem_{self.generation * 31 + index + 5}': label for index, label in enumerate(LABELS)}
        text = (f'snapshot={self.receipt}; bundle_id={BUNDLE}; window_id=1; action_outcome=dispatched_unverified\n'
                f'Display value: {self.value}\nasynchronous_update_pending={str(bool(self.pending)).lower()}\n')
        text += '\n'.join(f'{element} - button - label: {label} - identifier: {label} - actionable=true'
                          for element, label in self.elements.items())
        jpeg = None
        if success:
            self.renderer.stdin.write(json.dumps({'value': self.value}) + '\n')
            self.renderer.stdin.flush()
            jpeg = base64.b64decode(self.renderer.stdout.readline().strip())
            if not jpeg:
                raise RuntimeError('Fixture renderer failed')
        else:
            text = ('MC-INTEGRATION-01: invalid or stale fixture target; nessuna azione inviata. '
                    'Full resta attivo: acquisisci una nuova osservazione')
        return DeviceUseResult('synthetic-fixture', call_id,
            {'success': success, 'contentItems': [{'type': 'inputText', 'text': text}]}, jpeg, None, 0)

    def invoke(self, tool, arguments, call_id):
        action = arguments.get('action')
        if tool != 'mac_peekaboo' or arguments.get('bundle_id') != BUNDLE:
            raise RuntimeError('Synthetic test permits no actual native target')
        if action in {'observe', 'observe_app'}:
            if self.pending:
                self.apply(self.pending)
                self.pending = None
            self.trace.append({'action': action, 'display': self.value})
            return self.result(call_id)
        if (action == 'click' and arguments.get('snapshot') == self.receipt
            and arguments.get('element') in self.elements and not self.pending):
            self.pending = self.elements[arguments['element']]
            self.trace.append({'action': action, 'label': self.pending, 'display_before': self.value})
            return self.result(call_id)
        self.trace.append({'action': action, 'rejected_before_dispatch': True})
        return self.result(call_id, False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort', required=True)
    parser.add_argument('--left', type=int, default=17)
    parser.add_argument('--right', type=int, default=23)
    parser.add_argument('--chromium', default=shutil.which('google-chrome') or shutil.which('chromium'))
    args = parser.parse_args()
    if not args.chromium or not all(0 <= value <= 9999 for value in (args.left, args.right)):
        parser.error('Provide a local Chromium and operands between 0 and 9999.')
    fixture = CalculatorFixture(args.chromium)
    usage = []
    try:
        with tempfile.TemporaryDirectory(prefix='maverick-calculator-live-') as root:
            actor = CodexComputerActor(
                SimpleNamespace(session_id='live-changing-ids-fixture', workspace_id='default', runtime_root=root),
                SimpleNamespace(mode='full', approved_apps=(BUNDLE,), initial_app=BUNDLE),
                selection=SimpleNamespace(model_id=args.model, reasoning_effort=args.effort))
            try:
                expected = str(args.left * args.right)
                output, _ = actor.run({
                    'objective': f'Calculate {args.left} × {args.right} on the synthetic calculator in {BUNDLE}. Begin by clearing the display.',
                    'completion_criterion': f'The final fresh observation must show {expected} after {args.left} × {args.right}.',
                    'constraints': 'Use only the synthetic calculator. Its element IDs change on every observation. Each click has an asynchronous update; observe the same window again to settle it. No text input or other tools.',
                    'prepared_text': [],
                }, invoke=fixture.invoke, active=lambda: True, usage_sink=usage.append, timeout_seconds=90, max_steps=64)
                print(json.dumps({'boundary': 'synthetic native callback; no physical Mac input',
                    'result': output, 'display': fixture.value, 'trace': fixture.trace,
                    'models': sorted({entry['model_id'] for entry in usage}), 'effort': args.effort}, ensure_ascii=False))
                return 0 if output['status'] == 'completed' and fixture.value == expected else 1
            finally:
                actor.close()
    finally:
        fixture.close()


if __name__ == '__main__':
    sys.exit(main())
