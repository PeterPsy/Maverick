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
    active_rules = tuple(rules or builtin_rules())
    fallback = active_rules[-1]
    for rule in active_rules:
        if rule.rule_id == "generic/fallback":
            fallback = rule
            continue
        if _matches(rule, command=command, text=redacted_text):
            if rule.reducer == "json_large" and not _looks_like_json(redacted_text):
                continue
            return RuleSelection(rule_id=rule.rule_id, family=rule.family)
    return RuleSelection(rule_id=fallback.rule_id, family=fallback.family)


def _matches(rule: CompactionRule, *, command: str, text: str) -> bool:
    command_patterns = rule.compiled_command_patterns()
    text_patterns = rule.compiled_text_patterns()
    command_match = bool(command_patterns) and any(pattern.search(command) for pattern in command_patterns)
    text_match = bool(text_patterns) and any(pattern.search(text) for pattern in text_patterns)
    if command_patterns and not command_match:
        return False
    if text_patterns and not text_match:
        return False
    return command_match or text_match


def _looks_like_json(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return True
