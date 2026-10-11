"""Runtime-owned steps and effect checks for bounded UI tasks."""

from core.device_use.computer_observation import native_observation
from core.device_use.errors import DeviceUseUnavailableError


SELECTOR_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'minProperties': 1,
    'properties': {key: {'type': 'string', 'minLength': 1, 'maxLength': 200}
                   for key in ('label', 'identifier', 'role', 'value')},
}
EXPECTATION_SCHEMA = {**SELECTOR_SCHEMA, 'properties': {
    **SELECTOR_SCHEMA['properties'], 'text': {'type': 'string', 'minLength': 1, 'maxLength': 500}}}
STEP_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['tool', 'target', 'action', 'control', 'expect'],
    'properties': {
        'tool': {'type': 'string', 'enum': ['mac_peekaboo', 'mac_browser']},
        'target': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'action': {'type': 'string', 'enum': ['click', 'type', 'replace']},
        'control': SELECTOR_SCHEMA, 'expect': EXPECTATION_SCHEMA,
        'text': {'type': 'string', 'maxLength': 4000},
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
    keys = {'label', 'identifier', 'role', 'value'} | ({'text'} if expected else set())
    if (not isinstance(value, dict) or not value or set(value) - keys
        or any(not isinstance(item, str) or not item or len(item) > (500 if key == 'text' else 200)
               for key, item in value.items()) or ('text' in value and len(value) != 1)
        or (not expected and not (set(value) & {'label', 'identifier'}))):
        raise ValueError('computer_actor_selector_invalid')
    return dict(value)


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
    return {**value, 'control': validate_selector(value['control']),
            'expect': validate_selector(value['expect'], expected=True)}


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
        try:
            control = observed.resolve(step['control'])
        except ValueError as error:
            raise DeviceUseUnavailableError(str(error)) from error
        if step['tool'] == 'mac_peekaboo':
            native = {'action': step['action'], 'bundle_id': step['target'], 'snapshot': observed.receipt,
                      'element': control.element, 'observe_after': True}
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
                    and arguments.get('action') in {'observe', 'observe_app', 'list_windows'})
        if self.steps and arguments.get('action') not in {'observe', 'observe_app', 'list_windows', 'list_tabs'}:
            return False
        return True

    def record(self, tool, arguments, result):
        self.last_tool = tool
        self.last_target = arguments.get('bundle_id') or arguments.get('tab_id')
        observed = native_observation(result, tool, arguments)
        self.observation = observed
        if result.result.get('success') is False:
            texts = '\n'.join(item.get('text', '') for item in result.result.get('contentItems', []) if isinstance(item, dict))
            # A failed verification read being pre-dispatch does not undo the
            # previously dispatched input whose effect is still unknown.
            if (arguments.get('action') in {'click', 'type', 'replace'}
                and 'nessuna azione inviata' in texts.lower() and 'Full resta attivo' in texts):
                self.pending = None
        if self.pending is not None and observed and (observed.tool, observed.target) == (self.pending['tool'], self.pending['target']):
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
        return not self.completion_check or bool(self.observation and self.observation.verifies(self.completion_check))

    def state(self):
        state = {'verified_steps': self.index, 'total_steps': len(self.steps),
                 'effect_pending': self.pending is not None,
                 'next_input_allowed': self.pending is None,
                 'last_tool': self.last_tool, 'last_target': self.last_target}
        if self.steps and self.index < len(self.steps):
            state['current_step'] = self.steps[self.index]
        if self.pending:
            state['pending_effect'] = self.pending['expect']
        state['recent_verified_effects'] = self.history[-2:]
        return state
