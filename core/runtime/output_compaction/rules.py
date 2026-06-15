"""Built-in clean-room compaction rule declarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any


RULES_DIRECTORY = Path(__file__).with_name("builtin_rules")
RULE_TOP_LEVEL_FIELDS = frozenset({"id", "family", "priority", "reducer", "match"})
RULE_MATCH_FIELDS = frozenset({"command_regex_any", "text_regex_any"})


class RuleValidationError(ValueError):
    """Raised when a declarative compaction rule violates the schema."""


@dataclass(frozen=True)
class CompactionRule:
    """Declarative match metadata for a compaction reducer."""

    rule_id: str
    family: str
    priority: int
    reducer: str
    command_regex_any: tuple[str, ...] = ()
    text_regex_any: tuple[str, ...] = ()
    enabled: bool = True
    diagnostics: tuple[str, ...] = ()

    def compiled_command_patterns(self) -> tuple[re.Pattern[str], ...]:
        if not self.enabled:
            return ()
        return _compile_many(self.command_regex_any)

    def compiled_text_patterns(self) -> tuple[re.Pattern[str], ...]:
        if not self.enabled:
            return ()
        return _compile_many(self.text_regex_any)


def builtin_rules() -> tuple[CompactionRule, ...]:
    """Return built-in phase-1 rules in priority order."""
    rules = _load_builtin_rules()
    return tuple(sorted(rules, key=lambda item: item.priority, reverse=True))


def load_rules_from_directory(directory: Path) -> tuple[CompactionRule, ...]:
    """Load declarative compaction rules from one directory."""
    rules: list[CompactionRule] = []
    for path in sorted(Path(directory).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise RuleValidationError(f"{path.name}: rule payload must be an object")
        rules.append(load_rule_payload(payload, source=path.name))
    return tuple(sorted(rules, key=lambda item: item.priority, reverse=True))


def load_rule_payload(payload: Mapping[str, Any], *, source: str = "<memory>") -> CompactionRule:
    """Validate and convert one JSON rule declaration."""
    unknown = set(payload) - RULE_TOP_LEVEL_FIELDS
    if unknown:
        raise RuleValidationError(f"{source}: unknown rule fields: {', '.join(sorted(unknown))}")

    rule_id = _required_string(payload, "id", source=source)
    family = _required_string(payload, "family", source=source)
    reducer = _required_string(payload, "reducer", source=source)
    priority = _required_int(payload, "priority", source=source)
    match = payload.get("match", {})
    if match is None:
        match = {}
    if not isinstance(match, Mapping):
        raise RuleValidationError(f"{source}: match must be an object")
    unknown_match = set(match) - RULE_MATCH_FIELDS
    if unknown_match:
        raise RuleValidationError(f"{source}: unknown match fields: {', '.join(sorted(unknown_match))}")

    command_regex_any = _string_tuple(
        match.get("command_regex_any", ()),
        source=source,
        field="match.command_regex_any",
    )
    text_regex_any = _string_tuple(
        match.get("text_regex_any", ()),
        source=source,
        field="match.text_regex_any",
    )
    diagnostics = _regex_diagnostics(rule_id, "command_regex_any", command_regex_any) + _regex_diagnostics(
        rule_id,
        "text_regex_any",
        text_regex_any,
    )
    return CompactionRule(
        rule_id=rule_id,
        family=family,
        priority=priority,
        reducer=reducer,
        command_regex_any=command_regex_any,
        text_regex_any=text_regex_any,
        enabled=not diagnostics,
        diagnostics=diagnostics,
    )


def rule_diagnostics(rules: tuple[CompactionRule, ...] | None = None) -> tuple[str, ...]:
    """Return non-sensitive diagnostics for disabled declarative rules."""
    active_rules = builtin_rules() if rules is None else rules
    return tuple(diagnostic for rule in active_rules for diagnostic in rule.diagnostics)


@lru_cache(maxsize=1)
def _load_builtin_rules() -> tuple[CompactionRule, ...]:
    return load_rules_from_directory(RULES_DIRECTORY)


def _required_string(payload: Mapping[str, Any], field: str, *, source: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuleValidationError(f"{source}: {field} must be a non-empty string")
    return value.strip()


def _required_int(payload: Mapping[str, Any], field: str, *, source: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int):
        raise RuleValidationError(f"{source}: {field} must be an integer")
    return value


def _string_tuple(value: Any, *, source: str, field: str) -> tuple[str, ...]:
    if value in (None, ()):
        return ()
    if not isinstance(value, list):
        raise RuleValidationError(f"{source}: {field} must be a list of strings")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise RuleValidationError(f"{source}: {field}[{index}] must be a non-empty string")
        result.append(item)
    return tuple(result)


def _regex_diagnostics(rule_id: str, field: str, patterns: tuple[str, ...]) -> tuple[str, ...]:
    diagnostics: list[str] = []
    for pattern in patterns:
        try:
            re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as error:
            diagnostics.append(f"{rule_id}:{field}:invalid_regex:{error.__class__.__name__}")
    return tuple(diagnostics)


def _compile_many(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:
            continue
    return tuple(compiled)
