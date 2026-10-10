"""Only native-declared recovery may keep a bounded UI operator running."""

import json

from core.device_use.result_facts import native_result_facts


_PEEKABOO_READS = frozenset({"list_windows", "observe", "observe_app"})
_WINDOW_REFRESH = frozenset({"MC-PEEKABOO-25", "MC-PEEKABOO-27"})
_UNCERTAIN_INPUT = frozenset({"MC-PEEKABOO-20", "MC-PEEKABOO-21", "MC-PEEKABOO-23"})
_PARTIAL_INPUT = "MC-PEEKABOO-22"
_PRE_DISPATCH_RECOVERY = "Questo errore pre-dispatch non blocca il turno:"
_FULL_RECOVERY = "Full resta attivo: acquisisci una nuova osservazione"
_COMPANION_RECOVERY = frozenset({"MC-COMPANION-03", "MC-COMPANION-04"})
_RECEIPT_AND_OBSERVATION_FIELDS = frozenset({
    "snapshot", "observation_id", "window_id", "observe_after", "details", "image_max_dimension",
})
_PEEKABOO_INPUT_FIELDS = {
    "click": ("element",), "double_click": ("element",), "right_click": ("element",),
    "type": ("element", "text"), "replace": ("element", "text"),
    "click_point": ("point_x", "point_y"),
    "type_at_point": ("point_x", "point_y", "text"),
    "replace_at_point": ("point_x", "point_y", "text"),
    "press": ("key",), "scroll": ("element", "direction", "amount"), "launch_app": (),
}
_BROWSER_INPUT_FIELDS = {
    "click": ("x", "y"), "double_click": ("x", "y"), "right_click": ("x", "y"),
    "hover": ("x", "y"), "type_text": ("text",), "replace_text": ("text",),
    "keypress": ("key", "shift"), "scroll": ("x", "y", "direction", "amount"),
    "navigate": ("url",), "close_tab": (), "select_tab": (),
}
_BROWSER_INPUT_DEFAULTS = {"x": 0.5, "y": 0.5, "amount": 300, "shift": False}


class ComputerActorRecovery:
    def __init__(self, initial_app):
        self.selected_app = initial_app
        self.pending = None
        self.refresh_required = False
        self.uncertain_inputs = set()
        self.failures = []
        self.completion_verified = False
        self.pending_close = False

    def permits(self, tool, arguments):
        if not isinstance(arguments, dict):
            return False
        if self._input_key(tool, arguments) in self.uncertain_inputs:
            return False
        if self.pending is None:
            return True
        engine, bundle = self.pending
        if engine == "mac_browser" and self.pending_close and tool == engine and arguments.get("action") == "list_tabs":
            return True
        if self.refresh_required and arguments.get("action") != "list_windows":
            return False
        return (tool == engine and self._target(tool, arguments) == bundle
                and arguments.get("action") in (_PEEKABOO_READS if engine == "mac_peekaboo" else {"observe"}))

    def record(self, tool, arguments, result):
        """Return false for a refusal, unknown failure or undeclared recovery."""
        action = arguments.get("action")
        self.completion_verified = False
        if result.result.get("success") is True:
            tab_ids = self._tab_inventory(tool, arguments, result)
            self.completion_verified = result.image_jpeg is not None or tab_ids is not None
            if tool == "mac_computer" and action == "select_app":
                self.selected_app = arguments.get("bundle_id")
            if self.pending and action == "list_windows":
                self.refresh_required = False
            elif self.pending and action in {"observe", "observe_app"} and result.image_jpeg is not None:
                self.pending = None
                self.pending_close = False
            elif self.pending_close and tab_ids is not None and self.pending[1] not in tab_ids:
                self.pending = None
                self.pending_close = False
            return True
        if result.result.get("success") is not False:
            return False
        code = native_result_facts(result.result)["failure_reason_code"]
        items = result.result.get("contentItems") or []
        text = items[0].get("text", "") if items and isinstance(items[0], dict) else ""
        bundle = self._target(tool, arguments)
        if not bundle:
            return False
        if tool == "mac_browser" and code in _COMPANION_RECOVERY:
            self.pending = (tool, bundle)
            self.pending_close = code == "MC-COMPANION-04" and action == "close_tab"
            if code == "MC-COMPANION-04" and action != "observe":
                self.uncertain_inputs.add(self._input_key(tool, arguments))
        elif tool == "mac_peekaboo" and code in _WINDOW_REFRESH and action in {"observe", "observe_app"}:
            self.pending = (tool, bundle)
            self.refresh_required = True
        elif (tool == "mac_peekaboo" and (code in _UNCERTAIN_INPUT or code == _PARTIAL_INPUT)
              and action not in _PEEKABOO_READS):
            if code == _PARTIAL_INPUT and _FULL_RECOVERY not in text:
                return False
            self.pending = (tool, bundle)
            self.uncertain_inputs.add(self._input_key(tool, arguments))
        elif tool in {"mac_computer", "mac_peekaboo"} and _PRE_DISPATCH_RECOVERY in text:
            self.pending = (tool, bundle)
            if tool == "mac_computer":
                self.selected_app = bundle
        else:
            return False
        self.failures.append(code)
        return True

    def evidence(self, observed):
        if not self.failures:
            return observed
        return ("Native recovery: " + ", ".join(dict.fromkeys(self.failures)) + ". " + observed)[:3000]

    def _target(self, tool, arguments):
        if tool == "mac_browser":
            return arguments.get("tab_id")
        return arguments.get("bundle_id") or (self.selected_app if tool == "mac_computer" else None)

    @staticmethod
    def _tab_inventory(tool, arguments, result):
        """A native tab inventory can verify closure without imaging a closed tab."""
        if tool != "mac_browser" or arguments.get("action") != "list_tabs":
            return None
        items = result.result.get("contentItems") or []
        try:
            inventory = json.loads(items[0]["text"])
            if (inventory.get("execution_environment") == "parallel_companion"
                and inventory.get("tabs_complete") is True
                and isinstance(inventory.get("tabs"), list)
                and all(isinstance(tab, dict) and isinstance(tab.get("tab_id"), str)
                        and tab["tab_id"] for tab in inventory["tabs"])):
                return {tab["tab_id"] for tab in inventory["tabs"]}
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            pass
        return None

    @staticmethod
    def _input_key(tool, arguments):
        # Compare the dispatched action independently of receipt and observation settings.
        action = arguments.get("action")
        if tool == "mac_peekaboo" and action in _PEEKABOO_INPUT_FIELDS:
            return (tool, action, arguments.get("bundle_id"),
                    tuple(arguments.get(field) for field in _PEEKABOO_INPUT_FIELDS[action]))
        if tool == "mac_browser" and action in _BROWSER_INPUT_FIELDS:
            return (tool, action, arguments.get("tab_id"),
                    tuple(arguments.get(field, _BROWSER_INPUT_DEFAULTS.get(field))
                          for field in _BROWSER_INPUT_FIELDS[action]))
        target = {key: value for key, value in arguments.items()
                  if key not in _RECEIPT_AND_OBSERVATION_FIELDS}
        return tool, json.dumps(target, sort_keys=True, ensure_ascii=False)
