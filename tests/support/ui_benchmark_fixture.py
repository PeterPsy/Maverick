"""Four independent, rendered fixtures with changing receipts and delayed effects."""

import base64
import json
from pathlib import Path
import subprocess
import time

from core.device_use.models import DeviceUseResult


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = 'com.example.pc-use-benchmark'
LABELS = ['Clear', 'Seven', 'Eight', 'Nine', 'Multiply', 'Four', 'Five', 'Six',
          'One', 'Two', 'Three', 'Zero', 'Equals']
DIGITS = dict(zip(['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'], '0123456789'))
SCENARIOS = ('calculator', 'form', 'menu', 'async-save')


def control(label, role='button', value=None):
    return {'label': label, 'identifier': label, 'role': role, 'value': value,
            'actionable': role in {'button', 'textfield', 'menuitem'}}


class UIBenchmarkFixture:
    def __init__(self, scenario, chromium, *, render=True):
        self.scenario = scenario
        self.renderer = subprocess.Popen(['node', str(ROOT / 'tests/support/ui_benchmark_renderer.cjs'),
            str(ROOT / 'apps/browser/node_modules/playwright'), chromium], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) if render else None
        self.generation, self.receipt, self.elements = 0, '', {}
        self.pending, self.trace, self.results = None, [], []
        self.native_ms = 0.0
        self.value, self.left, self.operation, self.fresh = '0', None, None, True
        self.fields = {'Name': '', 'Email': '', 'Title': ''}
        self.status, self.menu_open, self.theme, self.saved, self.opened = 'Ready', False, 'Light', None, True

    def close(self):
        if self.renderer is None:
            return
        self.renderer.stdin.close()
        try:
            self.renderer.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.renderer.terminate()
            self.renderer.wait(timeout=5)
        self.renderer.stdout.close()
        self.renderer.stderr.close()

    def controls(self):
        if self.scenario == 'calculator':
            return [control('Display', 'statictext', self.value)] + [control(label) for label in LABELS]
        if self.scenario == 'form':
            return [control(key, 'textfield', self.fields[key]) for key in ('Name', 'Email')] + [
                control('Submit'), control('Status', 'statictext', self.status)]
        if self.scenario == 'menu':
            return [control('Theme'), control('Current theme', 'statictext', self.theme)] + (
                [control('Light', 'menuitem'), control('Dark', 'menuitem')] if self.menu_open else [])
        if self.opened:
            return [control('Title', 'textfield', self.fields['Title']), control('Save'), control('Close'),
                    control('Status', 'statictext', self.status)]
        return [control('Reopen'), control('Status', 'statictext', 'Closed')]

    def apply(self, action, label, text):
        if self.scenario == 'calculator':
            if label == 'Clear':
                self.value, self.left, self.operation, self.fresh = '0', None, None, True
            elif label in DIGITS:
                self.value = DIGITS[label] if self.fresh or self.value == '0' else self.value + DIGITS[label]
                self.fresh = False
            elif label == 'Multiply':
                self.left, self.operation, self.fresh = int(self.value), 'multiply', True
            elif label == 'Equals' and self.operation:
                right = int(self.value)
                self.value, self.fresh, self.operation = str(self.left * right), True, None
                self.results.append((self.left, right, self.value))
            else:
                raise ValueError('Unsupported calculator operation')
        elif action in {'replace', 'type'}:
            self.fields[label] = text if action == 'replace' else self.fields[label] + text
        elif label == 'Submit':
            self.status = 'Submitted' if self.fields['Name'] == 'Marco Test' and self.fields['Email'] == 'marco.test@example.invalid' else 'Invalid'
        elif label == 'Theme':
            self.menu_open = True
        elif label in {'Light', 'Dark'}:
            self.theme, self.menu_open = label, False
        elif label == 'Save':
            self.saved, self.status = self.fields['Title'], 'Saved'
        elif label == 'Close':
            self.opened, self.fields['Title'] = False, ''
        elif label == 'Reopen':
            self.opened, self.fields['Title'], self.status = True, self.saved or '', 'Loaded'
        else:
            raise ValueError('Unsupported fixture operation')

    def result(self, call_id, started, *, failure=None):
        self.generation += 1
        self.receipt = f'ps1_benchmark_{self.generation}'
        self.elements = {f'elem_{self.generation * 37 + index}': item for index, item in enumerate(self.controls())}
        text = f'snapshot={self.receipt}; bundle_id={BUNDLE}; window_id=1; action_outcome=dispatched_unverified\n'
        text += f'asynchronous_update_pending={str(self.pending is not None).lower()}\n'
        for element, item in self.elements.items():
            text += f"AX{item['role'].title()} (1 found):\n  {element} - {json.dumps(item['label'])} - identifier: {item['identifier']}"
            if item['value'] is not None:
                text += f" - value: {json.dumps(item['value'])}"
            if not item['actionable']:
                text += ' - [not actionable]'
            text += '\n'
        jpeg = None
        if failure is None:
            if self.renderer:
                self.renderer.stdin.write(json.dumps({'title': self.scenario, 'controls': self.controls(),
                    'columns': 4 if self.scenario == 'calculator' else 1}) + '\n')
                self.renderer.stdin.flush()
                jpeg = base64.b64decode(self.renderer.stdout.readline().strip())
                if not jpeg:
                    raise RuntimeError('Synthetic UI renderer failed')
            else:
                jpeg = b'unit-test-image'
        else:
            text = f'MC-INTEGRATION-01: {failure}; nessuna azione inviata. Full resta attivo: acquisisci una nuova osservazione'
        elapsed = (time.monotonic() - started) * 1000
        self.native_ms += elapsed
        return DeviceUseResult('synthetic-ui', call_id, {'success': failure is None,
            'contentItems': [{'type': 'inputText', 'text': text}]}, jpeg, None, elapsed)

    def invoke(self, tool, arguments, call_id):
        started = time.monotonic()
        if tool != 'mac_peekaboo' or arguments.get('bundle_id') != BUNDLE:
            raise RuntimeError('Benchmark has no native Mac connection')
        action = arguments.get('action')
        if action in {'observe', 'observe_app'}:
            if self.pending:
                self.pending['reads'] -= 1
                if self.pending['reads'] <= 0:
                    self.apply(self.pending['action'], self.pending['label'], self.pending['text'])
                    self.pending = None
            self.trace.append({'action': action, 'arguments': dict(arguments), 'state': self.state()})
            return self.result(call_id, started)
        if action == 'list_windows':
            self.trace.append({'action': action, 'arguments': dict(arguments), 'state': self.state()})
            return self.result(call_id, started)
        if (action not in {'click', 'type', 'replace'} or self.pending
            or arguments.get('snapshot') != self.receipt or arguments.get('element') not in self.elements):
            self.trace.append({'action': action, 'arguments': dict(arguments), 'rejected_before_dispatch': True})
            return self.result(call_id, started, failure='stale target or pending update')
        item = self.elements[arguments['element']]
        if not item['actionable'] or (action != 'click' and item['role'] != 'textfield'):
            self.trace.append({'action': action, 'arguments': dict(arguments), 'rejected_before_dispatch': True})
            return self.result(call_id, started, failure='control cannot accept this action')
        self.pending = {'action': action, 'label': item['label'], 'text': arguments.get('text', ''),
                        'reads': 2 if item['label'] == 'Save' else 1}
        if item['label'] == 'Save':
            self.status = 'Saving'
        self.trace.append({'action': action, 'arguments': dict(arguments), 'label': item['label'], 'text': arguments.get('text'), 'state_before': self.state()})
        return self.result(call_id, started)

    def state(self):
        return {'display': self.value, 'results': list(self.results), 'fields': dict(self.fields),
                'status': self.status, 'theme': self.theme, 'saved': self.saved, 'opened': self.opened,
                'effect_pending': self.pending is not None}

    def valid(self):
        if self.pending:
            return False
        if self.scenario == 'calculator':
            return self.results == [(17, 23, '391'), (27, 14, '378')] and self.value == '378'
        if self.scenario == 'form':
            return self.status == 'Submitted' and self.fields['Name'] == 'Marco Test' and self.fields['Email'] == 'marco.test@example.invalid'
        if self.scenario == 'menu':
            return self.theme == 'Dark' and not self.menu_open
        return self.saved == 'PC use benchmark' and self.fields['Title'] == self.saved and self.status == 'Loaded' and self.opened

    def task(self):
        objective, criterion, prepared = {
            'calculator': ('Calculate 17 × 23, then 27 × 14. Clear before each calculation.', 'Both results, 391 and 378, must be observed; final display 378.', []),
            'form': ('Fill Name with Marco Test and Email with marco.test@example.invalid, then Submit.', 'Fields retain the exact text and Status is Submitted.', ['Marco Test', 'marco.test@example.invalid']),
            'menu': ('Open Theme and select Dark.', 'Current theme is Dark and the menu is closed.', []),
            'async-save': ('Set Title to PC use benchmark, Save, wait for Saved, then Close and Reopen.', 'Reopened Title is PC use benchmark and Status is Loaded.', ['PC use benchmark']),
        }[self.scenario]
        return {'objective': objective + f' Use only {BUNDLE}.', 'completion_criterion': criterion,
                'constraints': 'Synthetic fixture: targets change IDs on every observation. Effects settle on a subsequent same-target read; Save requires two reads. Never replay a pending input. Use semantic labels when appropriate.',
                'prepared_text': prepared}
