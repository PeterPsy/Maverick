"""Rule selection for runtime tool-output compaction."""

from __future__ import annotations

import json
from typing import Iterable

from core.runtime.output_compaction.models import RuleSelection, ToolOutputCompactionInput
from core.runtime.output_compaction.rules import CompactionRule, builtin_rules


def classify_tool_output(
    compaction_input: ToolOutputCompactionInput,
    redacted_text: str,
    *,
    rules: Iterable[CompactionRule] | None = None,
) -> RuleSelection:
    """Select the highest-priority matching phase-1 rule."""
    command = " ".join(part for part in (compaction_input.command or "", " ".join(compaction_input.argv)) if part).strip()
    active_rules = tuple(rule for rule in (rules or builtin_rules()) if rule.enabled)
    fallback = CompactionRule(rule_id="generic/fallback", family="generic", priority=0, reducer="generic_fallback")
    if active_rules:
        fallback = active_rules[-1]
    for rule in active_rules:
        if rule.rule_id == "generic/fallback":
            fallback = rule
            continue
        if _command_matches(rule, command=command):
            if rule.reducer == "json_large" and not _looks_like_json(redacted_text):
                continue
            return RuleSelection(rule_id=rule.rule_id, family=rule.family)
    for rule in active_rules:
        if rule.rule_id == "generic/fallback":
            fallback = rule
            continue
        if _text_matches(rule, text=redacted_text):
            if rule.reducer == "json_large" and not _looks_like_json(redacted_text):
                continue
            return RuleSelection(rule_id=rule.rule_id, family=rule.family)
    return RuleSelection(rule_id=fallback.rule_id, family=fallback.family)


def _command_matches(rule: CompactionRule, *, command: str) -> bool:
    command_patterns = rule.compiled_command_patterns()
    return bool(command_patterns) and any(pattern.search(command) for pattern in command_patterns)


def _text_matches(rule: CompactionRule, *, text: str) -> bool:
    text_patterns = rule.compiled_text_patterns()
    return bool(text_patterns) and any(pattern.search(text) for pattern in text_patterns)


def _looks_like_json(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True
