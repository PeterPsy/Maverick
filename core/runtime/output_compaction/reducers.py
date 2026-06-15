"""Semantic reducers for phase-1 runtime tool output compaction."""

from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

from core.runtime.output_compaction.models import ReducerOutput, RuleSelection, ToolOutputCompactionInput, ToolOutputCompactionPolicy
from core.runtime.output_compaction.text import compact_by_context, strip_ansi, truncate_middle_bytes


GENERIC_IMPORTANT_PATTERN = re.compile(r"error|failed|failure|exception|traceback|panic|fatal|warning|assert", re.IGNORECASE)
PYTEST_IMPORTANT_PATTERN = re.compile(
    r"short test summary info|Traceback|FAILED|ERROR|AssertionError|E\s+|FAILURES|_+ .* _+",
    re.IGNORECASE,
)
NODE_IMPORTANT_PATTERN = re.compile(
    r"FAIL|Error:|AssertionError|expect\(|Received:|Expected:|\.spec\.|\.test\.|Test Files|playwright|browser",
    re.IGNORECASE,
)


def reduce_tool_output(
    selection: RuleSelection,
    compaction_input: ToolOutputCompactionInput,
    redacted_text: str,
    *,
    policy: ToolOutputCompactionPolicy,
    failed: bool,
) -> ReducerOutput:
    """Apply the selected reducer."""
    target = policy.failure_target_max_compacted_bytes if failed else policy.target_max_compacted_bytes
    if selection.rule_id == "tests/pytest_unittest":
        return _reduce_pytest_unittest(redacted_text, target_bytes=target, tail_lines=policy.failure_tail_lines)
    if selection.rule_id == "tests/node_runner":
        return _reduce_node_test_runner(redacted_text, target_bytes=target, tail_lines=policy.failure_tail_lines)
    if selection.rule_id == "vcs/git_status":
        return _reduce_git_status(redacted_text, target_bytes=target)
    if selection.rule_id == "data/json_large":
        json_result = _reduce_json_large(redacted_text, target_bytes=target)
        if json_result is not None:
            return json_result
    return _reduce_generic(redacted_text, compaction_input=compaction_input, target_bytes=target, tail_lines=policy.failure_tail_lines)


def _reduce_generic(
    value: str,
    *,
    compaction_input: ToolOutputCompactionInput,
    target_bytes: int,
    tail_lines: int,
) -> ReducerOutput:
    text = compact_by_context(
        value,
        important_pattern=GENERIC_IMPORTANT_PATTERN,
        head_lines=30,
        tail_lines=tail_lines,
        before=2,
        after=8,
        max_important_matches=80,
        target_bytes=target_bytes,
    )
    lines = strip_ansi(value).splitlines()
    facts = {
        "lines": len(lines),
        "error_lines": sum(1 for line in lines if re.search(r"error|failed|fatal|exception", line, re.IGNORECASE)),
    }
    if compaction_input.exit_code is not None:
        facts["exit_code"] = compaction_input.exit_code
    return ReducerOutput(text=text, facts=facts)


def _reduce_pytest_unittest(value: str, *, target_bytes: int, tail_lines: int) -> ReducerOutput:
    text = compact_by_context(
        value,
        important_pattern=PYTEST_IMPORTANT_PATTERN,
        head_lines=35,
        tail_lines=tail_lines,
        before=3,
        after=14,
        max_important_matches=80,
        target_bytes=target_bytes,
    )
    facts = _test_summary_counts(value)
    return ReducerOutput(text=text, facts=facts)


def _reduce_node_test_runner(value: str, *, target_bytes: int, tail_lines: int) -> ReducerOutput:
    text = compact_by_context(
        value,
        important_pattern=NODE_IMPORTANT_PATTERN,
        head_lines=35,
        tail_lines=tail_lines,
        before=3,
        after=14,
        max_important_matches=80,
        target_bytes=target_bytes,
    )
    facts = {
        "failed_lines": len(re.findall(r"(^|\s)FAIL(\s|$)", value, re.IGNORECASE | re.MULTILINE)),
        "error_lines": len(re.findall(r"Error:", value)),
    }
    for label in ("passed", "failed", "skipped"):
        match = re.search(rf"(\d+)\s+{label}", value, re.IGNORECASE)
        if match:
            facts[label] = int(match.group(1))
    return ReducerOutput(text=text, facts=facts)


def _reduce_git_status(value: str, *, target_bytes: int) -> ReducerOutput:
    lines = strip_ansi(value).splitlines()
    preserved: list[str] = []
    status_counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    current_section = ""
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if stripped.startswith("On branch") or "ahead of" in lower or "behind" in lower:
            preserved.append(stripped)
            continue
        if lower.endswith(":"):
            current_section = lower.rstrip(":")
            if "change" in current_section or "untracked" in current_section or "conflict" in current_section:
                preserved.append(stripped)
            continue
        status = _git_status_label(stripped, current_section)
        if status:
            status_counter[status] += 1
            samples.setdefault(status, [])
            if len(samples[status]) < 20:
                samples[status].append(stripped)
    summary = [f"{status}: {count}" for status, count in sorted(status_counter.items())]
    sample_lines = []
    for status, values in sorted(samples.items()):
        sample_lines.append(f"{status} samples:")
        sample_lines.extend(f"  {value}" for value in values)
    compacted = "\n".join(["git status summary", *preserved[:20], *summary, *sample_lines]).strip()
    facts: dict[str, Any] = {f"{status}_count": count for status, count in status_counter.items()}
    return ReducerOutput(text=truncate_middle_bytes(compacted, target_bytes), facts=facts)


def _reduce_json_large(value: str, *, target_bytes: int) -> ReducerOutput | None:
    stripped = value.strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    lines: list[str] = []
    facts: dict[str, Any] = {}
    if isinstance(payload, dict):
        keys = list(payload.keys())
        lines.append("json root: object")
        lines.append(f"top_level_key_count: {len(keys)}")
        lines.append("top_level_keys: " + ", ".join(str(key) for key in keys[:80]))
        facts["top_level_key_count"] = len(keys)
        for key in keys[:30]:
            if str(key).lower() in {"error", "message", "detail", "status", "code", "id", "name"}:
                lines.append(f"{key}: {_bounded_json(payload.get(key))}")
        for key in keys[:8]:
            value_at_key = payload.get(key)
            if isinstance(value_at_key, list):
                lines.append(f"{key}: array length {len(value_at_key)} sample {_bounded_json(_sample_list(value_at_key))}")
            elif isinstance(value_at_key, dict):
                lines.append(f"{key}: object keys {', '.join(str(item) for item in list(value_at_key.keys())[:20])}")
    elif isinstance(payload, list):
        lines.append("json root: array")
        lines.append(f"array_length: {len(payload)}")
        lines.append("sample: " + _bounded_json(_sample_list(payload)))
        facts["array_length"] = len(payload)
    else:
        lines.append(f"json root: {type(payload).__name__}")
        lines.append(_bounded_json(payload))
    return ReducerOutput(text=truncate_middle_bytes("\n".join(lines), target_bytes), facts=facts)


def _test_summary_counts(value: str) -> dict[str, int]:
    facts: dict[str, int] = {}
    for label in ("failed", "passed", "skipped", "errors", "error", "xfailed", "xpassed"):
        matches = re.findall(rf"(\d+)\s+{label}\b", value, re.IGNORECASE)
        if matches:
            key = "errors" if label == "error" else label
            facts[key] = max(facts.get(key, 0), max(int(item) for item in matches))
    failed_lines = re.findall(r"^FAILED\s+", value, re.MULTILINE)
    error_lines = re.findall(r"^ERROR\s+", value, re.MULTILINE)
    if failed_lines:
        facts["failed_tests"] = len(failed_lines)
    if error_lines:
        facts["error_entries"] = len(error_lines)
    return facts


def _git_status_label(stripped: str, section: str) -> str:
    lower = stripped.lower()
    if not stripped:
        return ""
    if lower.startswith(("modified:", "\tmodified:", "m ")):
        return "modified"
    if lower.startswith(("new file:", "\tnew file:", "a ")):
        return "added"
    if lower.startswith(("deleted:", "\tdeleted:", "d ")):
        return "deleted"
    if lower.startswith(("renamed:", "\trenamed:", "r ")):
        return "renamed"
    if "untracked" in section and not lower.startswith("("):
        return "untracked"
    if "conflict" in section or lower.startswith(("both modified:", "unmerged:")):
        return "conflicted"
    return ""


def _bounded_json(value: Any) -> str:
    return truncate_middle_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), 600).replace("\n", " ")


def _sample_list(value: list[Any]) -> list[Any]:
    if len(value) <= 6:
        return value
    return [*value[:3], "...", *value[-3:]]
