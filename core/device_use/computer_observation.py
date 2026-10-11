"""Exact, current UI targets from native receipts; no inferred selectors."""

from dataclasses import dataclass, field
import json
import re


def normalized(value):
    # AX display values may carry Unicode bidi marks, not visible content.
    return str(value).translate(dict.fromkeys(map(ord, '\u200e\u200f\u202a\u202b\u202c\u2066\u2067\u2068\u2069'))).strip()


def role_name(value):
    return str(value).removeprefix('AX').replace('_', '').lower()


@dataclass
class NativeControl:
    element: str
    label: str = ''
    role: str = ''
    identifier: str = ''
    value: str | None = None
    actionable: bool = False
    x: float | None = None
    y: float | None = None

    def matches(self, selector):
        return all((role_name(self.role) == role_name(value) if key == 'role' else
                    normalized(getattr(self, key, None)) == normalized(value))
                   for key, value in selector.items())


@dataclass
class NativeObservation:
    tool: str
    target: str
    receipt: str
    controls: list[NativeControl] = field(default_factory=list)
    text: str = ''
    window_id: int | None = None
    fresh: bool = True

    def resolve(self, selector):
        matches = [control for control in self.controls if control.actionable and control.matches(selector)]
        if len(matches) != 1:
            raise ValueError('computer_actor_target_ambiguous' if matches else 'computer_actor_target_missing')
        return matches[0]

    def verifies(self, expectation):
        if set(expectation) == {'text'}:
            visible = {normalized(line) for line in self.text.splitlines()}
            for control in self.controls:
                visible.add(normalized(control.label))
                if control.value is not None:
                    visible.add(normalized(control.value))
                    visible.add(normalized(control.label) + ': ' + normalized(control.value))
            return normalized(expectation['text']) in visible
        return any(control.matches(expectation) for control in self.controls)


def native_observation(result, tool, arguments):
    if result.result.get('success') is not True or result.image_jpeg is None:
        return None
    text = '\n'.join(item.get('text', '') for item in result.result.get('contentItems', []) if isinstance(item, dict))
    if tool == 'mac_browser':
        try:
            data = json.loads(text)
            receipt, target = data['observation_id'], data['tab_id']
            page = data['page']
            controls = [NativeControl(str(index), item.get('label', ''), item.get('kind', ''),
                value=item.get('value'), actionable=not item.get('disabled', False), x=item.get('x'), y=item.get('y'))
                for index, item in enumerate(page.get('controls', [])) if isinstance(item, dict)]
            if not isinstance(receipt, str) or not isinstance(target, str):
                return None
            return NativeObservation(tool, target, receipt, controls, page.get('text', ''))
        except (ValueError, KeyError, TypeError, AttributeError):
            return None
    if tool != 'mac_peekaboo':
        return None
    receipt = re.search(r'\bsnapshot=(ps1_[\w-]+)', text)
    bundle = re.search(r'\bbundle_id=([\w.-]+)', text)
    if not receipt or not bundle:
        return None
    window = re.search(r'\bwindow_id=(\d+)', text)
    controls, role = [], ''
    for line in text.splitlines():
        heading = re.match(r'\s*(AX\w+)\s*\(', line)
        if heading:
            role = heading[1]
        match = re.match(r'\s*(elem_[\w-]+)\s*-\s*"([^"]*)"', line)
        if match:
            value = re.search(r'\bvalue:\s*"([^"]*)"', line)
            identifier = re.search(r'\bidentifier:\s*(.*?)(?:\s+-\s+|$)', line)
            controls.append(NativeControl(match[1], match[2], role,
                identifier[1].strip() if identifier else '', value[1] if value else None,
                '[not actionable]' not in line and role_name(role) in {'button', 'textfield', 'textarea', 'menuitem', 'checkbox', 'combobox'}))
            continue
        # Compact, line-oriented native fixtures and future receipt projections.
        match = re.match(r'\s*(elem_[\w-]+)\s*-\s*(\w+)\s*-\s*label:\s*(.*?)(?:\s+-\s+|$)', line)
        if match:
            identifier = re.search(r'\bidentifier:\s*(.*?)(?:\s+-\s+|$)', line)
            value = re.search(r'\bvalue:\s*(.*?)(?:\s+-\s+|$)', line)
            controls.append(NativeControl(match[1], match[3], match[2],
                identifier[1] if identifier else '', value[1] if value else None,
                'actionable=true' in line))
    return NativeObservation(tool, bundle[1], receipt[1], controls, text, int(window[1]) if window else None)
