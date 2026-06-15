"""Text helpers for bounded runtime output payloads."""

from __future__ import annotations

import re


ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def byte_len(value: str) -> int:
    """Return UTF-8 byte length for event payload accounting."""
    return len(value.encode("utf-8", errors="replace"))


def strip_ansi(value: str) -> str:
    """Remove ANSI escape sequences from provider text output."""
    return ANSI_ESCAPE_PATTERN.sub("", value)


def truncate_bytes(value: str, max_bytes: int) -> str:
    """Return a UTF-8 safe prefix bounded by max_bytes."""
    if max_bytes <= 0:
        return ""
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def truncate_middle_bytes(value: str, max_bytes: int, *, marker: str = "\n[... omitted ...]\n") -> str:
    """Bound text by preserving both the beginning and diagnostic tail."""
    if max_bytes <= 0:
        return ""
    if byte_len(value) <= max_bytes:
        return value
    marker_bytes = byte_len(marker)
    if marker_bytes >= max_bytes:
        return truncate_bytes(marker, max_bytes)
    head_budget = max(0, (max_bytes - marker_bytes) // 3)
    tail_budget = max(0, max_bytes - marker_bytes - head_budget)
    head = truncate_bytes(value, head_budget)
    tail_encoded = value.encode("utf-8", errors="replace")[-tail_budget:] if tail_budget else b""
    tail = tail_encoded.decode("utf-8", errors="ignore")
    return f"{head}{marker}{tail}"


def dedupe_adjacent_lines(lines: list[str]) -> list[str]:
    """Collapse adjacent duplicate lines without hiding non-adjacent repeats."""
    result: list[str] = []
    last: str | None = None
    duplicate_count = 0
    for line in lines:
        if line == last:
            duplicate_count += 1
            continue
        if duplicate_count:
            result.append(f"[repeated previous line {duplicate_count} more times]")
            duplicate_count = 0
        result.append(line)
        last = line
    if duplicate_count:
        result.append(f"[repeated previous line {duplicate_count} more times]")
    return result


def compact_by_context(
    value: str,
    *,
    important_pattern: re.Pattern[str],
    head_lines: int,
    tail_lines: int,
    before: int,
    after: int,
    max_important_matches: int,
    target_bytes: int,
) -> str:
    """Keep head/tail plus context around important diagnostic lines."""
    stripped = strip_ansi(value)
    lines = stripped.splitlines()
    if not lines:
        return truncate_middle_bytes(stripped, target_bytes)

    selected: set[int] = set(range(min(head_lines, len(lines))))
    selected.update(range(max(0, len(lines) - tail_lines), len(lines)))
    matches = 0
    for index, line in enumerate(lines):
        if not important_pattern.search(line):
            continue
        matches += 1
        if matches > max_important_matches:
            continue
        selected.update(range(max(0, index - before), min(len(lines), index + after + 1)))

    compacted_lines: list[str] = []
    previous_index: int | None = None
    for index in sorted(selected):
        if previous_index is not None and index > previous_index + 1:
            omitted = index - previous_index - 1
            compacted_lines.append(f"[... omitted {omitted} lines ...]")
        compacted_lines.append(lines[index])
        previous_index = index

    compacted = "\n".join(dedupe_adjacent_lines(compacted_lines)).strip()
    if not compacted:
        compacted = "\n".join(lines[:head_lines] + lines[-tail_lines:]).strip()
    return truncate_middle_bytes(compacted, target_bytes)
