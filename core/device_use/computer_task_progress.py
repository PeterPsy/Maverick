"""Runtime-owned steps and effect checks for bounded UI tasks."""

from core.device_use.computer_observation import current_selector, native_observation, normalized_region
from core.device_use.errors import DeviceUseUnavailableError


FLAT_SELECTOR_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'minProperties': 1,
    'properties': {**{key: {'type': 'string', 'minLength': 1, 'maxLength': 200}
                   for key in ('label', 'identifier', 'role', 'value')},
        'region': {'type': 'object', 'additionalProperties': False,
            'description': 'Normalized rectangle in the captured image, origin top left. Restricts locally recognized image text; never guesses a click point.',
            'required': ['x', 'y', 'width', 'height'], 'properties': {
                **{key: {'type': 'number', 'minimum': 0, 'exclusiveMaximum': 1} for key in ('x', 'y')},
                **{key: {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 1} for key in ('width', 'height')}}}},
    'anyOf': [{'required': ['label']}, {'required': ['identifier']}],
}
FLAT_EXPECTATION_SCHEMA = {key: value for key, value in FLAT_SELECTOR_SCHEMA.items() if key != 'anyOf'}
FLAT_EXPECTATION_SCHEMA['anyOf'] = [{'required': [key]} for key in ('label', 'identifier', 'role', 'value')]
TEXT_EXPECTATION_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['text'],
    'properties': {'text': {'type': 'string', 'minLength': 1, 'maxLength': 500}},
}


def representation_schema(ax, pixel):
    return {'type': 'object', 'additionalProperties': False, 'required': ['ax', 'pixel'],
            'description': 'Explicit alternatives for the same native control/effect. The current capture selects ax or pixel; neither branch is an alias or fallback. Pixel predicates require region.',
            'properties': {'ax': ax, 'pixel': {**pixel, 'required': ['region']}}}


SELECTOR_SCHEMA = {'anyOf': [FLAT_SELECTOR_SCHEMA,
    representation_schema(FLAT_SELECTOR_SCHEMA, FLAT_SELECTOR_SCHEMA)]}
FLAT_EFFECT_SCHEMA = {'anyOf': [FLAT_EXPECTATION_SCHEMA, TEXT_EXPECTATION_SCHEMA]}
EXPECTATION_SCHEMA = {
    'description': 'Expected visible effect. Exact selectors or text alone (exact label, value, label: value, or standalone line). Native ax/pixel alternatives allow representation changes; each pixel effect needs its own region.',
    'anyOf': [FLAT_EXPECTATION_SCHEMA, TEXT_EXPECTATION_SCHEMA,
              representation_schema(FLAT_EFFECT_SCHEMA, FLAT_EXPECTATION_SCHEMA)],
}
STEP_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['tool', 'target', 'action', 'control', 'expect'],
    'properties': {
        'tool': {'type': 'string', 'enum': ['mac_peekaboo', 'mac_browser']},
        'target': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'action': {'type': 'string', 'enum': ['click', 'type', 'replace']},
        'control': SELECTOR_SCHEMA, 'expect': EXPECTATION_SCHEMA,
        'text': {'type': 'string', 'maxLength': 4000},
        'window_id': {'type': 'integer', 'minimum': 1, 'maximum': 4294967295,
                      'description': 'Exact native window from the current app inventory; mac_peekaboo only.'},
    },
}
SEMANTIC_TOOL = {
    'type': 'function', 'name': 'ui_action',
    'description': 'Resolve an exact label/identifier in the current observation and perform one verified step. When steps are supplied, call only with step_index. Pending effects require same-target reads, never replay.',
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': {
        'step_index': {'type': 'integer', 'minimum': 0, 'maximum': 31},
        **STEP_SCHEMA['properties'],
    }},
}


def validate_selector(value, *, expected=False):
    if isinstance(value, dict) and set(value) == {'ax', 'pixel'}:
        if any(not isinstance(branch, dict) or 'ax' in branch or 'pixel' in branch
               for branch in value.values()):
            raise ValueError('computer_actor_selector_invalid')
        ax = validate_selector(value['ax'], expected=expected)
        pixel = validate_selector(value['pixel'], expected=expected)
        if 'region' not in pixel:
            raise ValueError('computer_actor_selector_invalid')
        return {'ax': ax, 'pixel': pixel}
    keys = {'label', 'identifier', 'role', 'value', 'region'} | ({'text'} if expected else set())
    if (not isinstance(value, dict) or not value or set(value) - keys
        or any(not isinstance(item, str) or not item or len(item) > (500 if key == 'text' else 200)
               for key, item in value.items() if key != 'region') or ('text' in value and len(value) != 1)
        or (set(value) == {'region'})
        or (not expected and not (set(value) & {'label', 'identifier'}))):
        raise ValueError('computer_actor_selector_invalid')
    return {**value, **({'region': normalized_region(value['region'])} if 'region' in value else {})}


def validate_step(value, prepared_text):
    if (not isinstance(value, dict) or set(value) - set(STEP_SCHEMA['properties'])
        or not set(STEP_SCHEMA['required']) <= set(value)
        or value['tool'] not in {'mac_peekaboo', 'mac_browser'}
        or value['action'] not in {'click', 'type', 'replace'}
        or not isinstance(value['target'], str) or not 0 < len(value['target']) <= 200
        or (value['action'] != 'click' and (value.get('text') not in prepared_text
             or value['tool'] != 'mac_peekaboo'))
        or (value['action'] == 'click' and 'text' in value)):
        raise ValueError('computer_actor_step_invalid')
    if 'window_id' in value and (value['tool'] != 'mac_peekaboo'
        or type(value['window_id']) is not int or not 1 <= value['window_id'] <= 4294967295):
        raise ValueError('computer_actor_step_invalid')
    control = validate_selector(value['control'])
    expect = validate_selector(value['expect'], expected=True)
    if value['tool'] != 'mac_peekaboo' and ('ax' in control or 'ax' in expect):
        raise ValueError('computer_actor_step_invalid')
    return {**value, 'control': control, 'expect': expect}


class ComputerTaskProgress:
    def __init__(self, task):
        self.steps = task.get('steps', [])
        self.prepared_text = task.get('prepared_text', [])
        self.index = 0
        self.pending = None
        self.pending_reads = 0
        self.observation = None
        self.last_target = None
        self.last_tool = None
        self.history = []
        self.completion_check = task.get('completion_check')
        self.effect_was_present = False
        self.detailed_windows = set()

    def prepare(self, arguments):
        if self.pending is not None:
            raise DeviceUseUnavailableError('computer_actor_effect_pending')
        if self.steps:
            if set(arguments) != {'step_index'} or type(arguments['step_index']) is not int or arguments['step_index'] != self.index or self.index >= len(self.steps):
                raise DeviceUseUnavailableError('computer_actor_step_mismatch')
            step = self.steps[self.index]
        else:
            try:
                step = validate_step(arguments, self.prepared_text)
            except ValueError as error:
                raise DeviceUseUnavailableError(str(error)) from error
        observed = self.observation
        if not observed or not observed.fresh or (observed.tool, observed.target) != (step['tool'], step['target']):
            raise DeviceUseUnavailableError('computer_actor_fresh_observation_required')
        if 'window_id' in step and observed.window_id != step['window_id']:
            raise DeviceUseUnavailableError('computer_actor_exact_window_required')
        if observed.pixels_only and step['action'] != 'click':
            raise DeviceUseUnavailableError('computer_actor_pixel_text_click_only')
        if observed.pixels_only and (
            'region' not in current_selector(step['control'], pixels_only=True)
            or 'region' not in current_selector(step['expect'], pixels_only=True)):
            raise DeviceUseUnavailableError('computer_actor_pixel_region_required')
        try:
            control = observed.resolve(step['control'])
        except ValueError as error:
            raise DeviceUseUnavailableError(str(error)) from error
        if step['tool'] == 'mac_peekaboo':
            native = {'bundle_id': step['target'], 'snapshot': observed.receipt, 'observe_after': True}
            if (observed.target, observed.window_id) in self.detailed_windows:
                native['details'] = True
            if observed.pixels_only:
                native.update(action='click_point', point_x=control.x, point_y=control.y)
            else:
                native.update(action=step['action'], element=control.element)
        else:
            if step['action'] != 'click' or control.x is None or control.y is None:
                raise DeviceUseUnavailableError('computer_actor_step_invalid')
            native = {'action': 'click', 'tab_id': step['target'], 'observation_id': observed.receipt,
                      'x': control.x, 'y': control.y, 'observe_after': True}
        if 'text' in step:
            native['text'] = step['text']
        observed.fresh = False
        self.effect_was_present = observed.verifies(step['expect'])
        self.pending = step
        self.pending_reads = 0
        return step['tool'], native

    def permits(self, tool, arguments):
        if self.pending is not None:
            target = arguments.get('bundle_id') if tool == 'mac_peekaboo' else arguments.get('tab_id')
            return (tool == self.pending['tool'] and target == self.pending['target']
                    and ('window_id' not in self.pending or
                         (arguments.get('action') == 'list_windows' or
                          (arguments.get('action') == 'observe' and
                           arguments.get('window_id') == self.pending['window_id'])))
                    and arguments.get('action') in {'observe', 'observe_app', 'list_windows'})
        if self.steps and arguments.get('action') not in {'observe', 'observe_app', 'list_windows', 'list_tabs'}:
            return False
        return True

    def observation_arguments(self, tool, arguments):
        # A compact read of a deep web view can remove the controls just
        # resolved by a detailed read. Preserve the escalation for this exact
        # planned window, including across model/context checkpoints.
        if (self.steps and tool == 'mac_peekaboo' and arguments.get('action') == 'observe'
            and (arguments.get('bundle_id'), arguments.get('window_id')) in self.detailed_windows):
            return {**arguments, 'details': True}
        return arguments

    def record(self, tool, arguments, result):
        self.last_tool = tool
        self.last_target = arguments.get('bundle_id') or arguments.get('tab_id')
        observed = native_observation(result, tool, arguments)
        self.observation = observed
        if (self.steps and observed and tool == 'mac_peekaboo' and observed.window_id is not None
            and (arguments.get('details') is True or not observed.text_complete)):
            self.detailed_windows.add((observed.target, observed.window_id))
        if result.result.get('success') is False:
            texts = '\n'.join(item.get('text', '') for item in result.result.get('contentItems', []) if isinstance(item, dict))
            # A failed verification read being pre-dispatch does not undo the
            # previously dispatched input whose effect is still unknown.
            if (arguments.get('action') in {'click', 'click_point', 'type', 'replace'}
                and 'nessuna azione inviata' in texts.lower() and 'Full resta attivo' in texts):
                self.pending = None
        if (self.pending is not None and observed and
            (observed.tool, observed.target) == (self.pending['tool'], self.pending['target']) and
            ('window_id' not in self.pending or observed.window_id == self.pending['window_id'])):
            settling = 'asynchronous_update_pending=true' in observed.text
            same_immediate_effect = self.effect_was_present and arguments.get('action') not in {'observe', 'observe_app'}
            if observed.verifies(self.pending['expect']) and not settling and not same_immediate_effect:
                self.history.append({'step_index': self.index, 'effect': self.pending['expect'], 'verified': True})
                self.index += 1
                self.pending = None
            elif arguments.get('action') in {'observe', 'observe_app'}:
                self.pending_reads += 1
                if self.pending_reads >= 3:
                    raise DeviceUseUnavailableError('computer_actor_effect_not_verified')

    def complete(self):
        if self.pending is not None or self.index < len(self.steps):
            return False
        if (self.steps and 'window_id' in self.steps[-1] and
            (self.observation is None or self.observation.window_id != self.steps[-1]['window_id'])):
            return False
        return not self.completion_check or bool(self.observation and self.observation.verifies(self.completion_check))

    def state(self):
        state = {'verified_steps': self.index, 'total_steps': len(self.steps),
                 'effect_pending': self.pending is not None,
                 'next_input_allowed': self.pending is None,
                 'last_tool': self.last_tool, 'last_target': self.last_target,
                 'completion_verified': self.complete(),
                 'observation_text_complete': bool(self.observation and self.observation.text_complete)}
        if self.steps and self.index < len(self.steps):
            state['current_step'] = self.steps[self.index]
        if self.pending:
            state['pending_effect'] = self.pending['expect']
        state['recent_verified_effects'] = self.history[-2:]
        return state
