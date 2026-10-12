"""Bounded actions against references issued by a Chrome snapshot."""

import re
from errors import BrowserValidationError

INTERACTION_ACTIONS = frozenset({"click", "type", "press_key", "hover", "select_option", "set_checked"})
INTERACTION_FIELDS = {
    "click": {"ref"}, "hover": {"ref"},
    "type": {"ref", "text"}, "press_key": {"ref", "key"},
    "select_option": {"ref", "values"}, "set_checked": {"ref", "checked"},
}
KEYS = frozenset({"Enter", "Tab", "Escape", "Backspace", "Delete", "Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"})


def validate_interaction(action: str, parameters: dict) -> None:
    ref = parameters.get("ref")
    if not isinstance(ref, str) or not re.fullmatch(r"c-[a-f0-9-]{36}-\d{1,4}", ref):
        raise BrowserValidationError("Use an element ref from a fresh Chrome snapshot.", field="ref")
    if action == "type" and (not isinstance(parameters.get("text"), str) or len(parameters["text"]) > 20_000):
        raise BrowserValidationError("text must contain at most 20000 characters.", field="text")
    if action == "press_key":
        key = parameters.get("key")
        if not isinstance(key, str) or key.removeprefix("Shift+") not in KEYS:
            raise BrowserValidationError("Choose a supported page key, optionally with Shift.", field="key")
    if action == "select_option":
        values = parameters.get("values")
        if not isinstance(values, list) or not 1 <= len(values) <= 20 or any(not isinstance(value, str) or len(value) > 1000 for value in values):
            raise BrowserValidationError("values must contain 1–20 bounded option values.", field="values")
    if action == "set_checked" and not isinstance(parameters.get("checked"), bool):
        raise BrowserValidationError("checked must be a boolean.", field="checked")
