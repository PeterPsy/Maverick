"""Exact, current UI targets from native receipts; no inferred selectors."""

from dataclasses import dataclass, field
import json
import math
import re


def normalized(value):
    # AX display values may carry Unicode bidi marks, not visible content.
    return str(value).translate(dict.fromkeys(map(ord, '\u200e\u200f\u202a\u202b\u202c\u2066\u2067\u2068\u2069'))).strip()


def role_name(value):
    return str(value).removeprefix('AX').replace('_', '').lower()


def normalized_region(value):
    if (not isinstance(value, dict) or set(value) != {'x', 'y', 'width', 'height'}
        or any(type(number) not in {int, float} or not math.isfinite(number) for number in value.values())
        or not (0 <= value['x'] < 1 and 0 <= value['y'] < 1
                and 0 < value['width'] <= 1 and 0 < value['height'] <= 1
                and value['x'] + value['width'] <= 1.000001
                and value['y'] + value['height'] <= 1.000001)):
        raise ValueError('computer_actor_region_invalid')
    return dict(value)


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
    bounds: dict | None = None

    def matches(self, selector):
        if 'region' in selector:
            if self.bounds is None:
                return False
            region, bounds = selector['region'], self.bounds
            if not (region['x'] <= bounds['x'] and region['y'] <= bounds['y']
                    and bounds['x'] + bounds['width'] <= region['x'] + region['width']
                    and bounds['y'] + bounds['height'] <= region['y'] + region['height']):
                return False
        return all((role_name(self.role) == role_name(value) if key == 'role' else
                    normalized(getattr(self, key, None)) == normalized(value))
                   for key, value in selector.items() if key != 'region')


@dataclass
class NativeObservation:
    tool: str
    target: str
    receipt: str
    controls: list[NativeControl] = field(default_factory=list)
    text: str = ''
    window_id: int | None = None
    fresh: bool = True
    pixels_only: bool = False

    def resolve(self, selector):
        matches = [control for control in self.controls if control.actionable and control.matches(selector)]
        if len(matches) != 1:
            raise ValueError('computer_actor_target_ambiguous' if matches else 'computer_actor_target_missing')
        return matches[0]

    def verifies(self, expectation):
        if self.pixels_only and 'region' not in expectation:
            return False
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
    receipt = re.search(r'\bsnapshot=((?:ps1|px1)_[\w-]+)', text)
    bundle = re.search(r'\bbundle_id=([\w.-]+)', text)
    if not receipt or not bundle:
        return None
    window = re.search(r'\bwindow_id=(\d+)', text)
    if receipt[1].startswith('px1_'):
        if not window or 'observation_mode=pixels_only' not in text:
            return None
        controls = []
        for line in text.splitlines():
            if ('pixel_text_source=same_capture' not in text
                or 'pixel_text_recognition_succeeded=true' not in text):
                break
            if not line.startswith('pixel_text='):
                continue
            try:
                item = json.loads(line.removeprefix('pixel_text='))
                label, confidence = item['label'], item['confidence']
                bounds = normalized_region(item['bounds'])
                if (not isinstance(label, str) or not label or len(label) > 200
                    or type(confidence) not in {int, float} or not math.isfinite(confidence)
                    or not 0.85 <= confidence <= 1 or len(controls) >= 600):
                    continue
                controls.append(NativeControl(str(len(controls)), label, 'image_text', value=label,
                    actionable=True, x=bounds['x'] + bounds['width'] / 2,
                    y=bounds['y'] + bounds['height'] / 2, bounds=bounds))
            except (ValueError, KeyError, TypeError):
                continue
        # These are locally recognized labels, never AX controls or text focus.
        return NativeObservation(tool, bundle[1], receipt[1], controls, text,
                                 int(window[1]), pixels_only=True)
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
