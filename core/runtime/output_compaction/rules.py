"""Built-in clean-room compaction rule declarations."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CompactionRule:
    """Declarative match metadata for a compaction reducer."""

    rule_id: str
    family: str
    priority: int
    reducer: str
    command_regex_any: tuple[str, ...] = ()
    text_regex_any: tuple[str, ...] = ()

    def compiled_command_patterns(self) -> tuple[re.Pattern[str], ...]:
        return _compile_many(self.command_regex_any)

    def compiled_text_patterns(self) -> tuple[re.Pattern[str], ...]:
        return _compile_many(self.text_regex_any)


def builtin_rules() -> tuple[CompactionRule, ...]:
    """Return built-in phase-1 rules in priority order."""
    rules = (
        CompactionRule(
            rule_id="tests/pytest_unittest",
            family="test_runner",
            priority=90,
            reducer="pytest_unittest",
            command_regex_any=(
                r"(^|\s)(pytest|python\s+-m\s+pytest)(\s|$)",
                r"(^|\s)(python\s+-m\s+unittest|unittest)(\s|$)",
            ),
            text_regex_any=(r"short test summary info", r"Traceback", r"FAILED", r"ERROR"),
        ),
        CompactionRule(
            rule_id="tests/node_runner",
            family="test_runner",
            priority=80,
            reducer="node_test_runner",
            command_regex_any=(
                r"(^|\s)(npm|pnpm|yarn)\s+test(\s|$)",
                r"(^|\s)(vitest|jest)(\s|$)",
                r"(^|\s)playwright\s+test(\s|$)",
            ),
            text_regex_any=(r"Test Files", r"FAIL", r"Error:", r"\.spec\.", r"\.test\."),
        ),
        CompactionRule(
            rule_id="vcs/git_status",
            family="version_control",
            priority=70,
            reducer="git_status",
            command_regex_any=(r"(^|\s)git\s+status(\s|$)",),
            text_regex_any=(r"On branch ", r"Changes not staged", r"Untracked files"),
        ),
        CompactionRule(
            rule_id="data/json_large",
            family="structured_data",
            priority=60,
            reducer="json_large",
            command_regex_any=(r"(^|\s)(curl|maverick|python)(\s|$)",),
            text_regex_any=(r"^\s*[\[{]",),
        ),
        CompactionRule(
            rule_id="generic/fallback",
            family="generic",
            priority=0,
            reducer="generic_fallback",
        ),
    )
    return tuple(sorted(rules, key=lambda item: item.priority, reverse=True))


def _compile_many(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE | re.MULTILINE))
        except re.error:
            continue
    return tuple(compiled)
