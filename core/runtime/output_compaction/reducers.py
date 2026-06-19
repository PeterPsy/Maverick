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
        if stripped.startswith("## ") or stripped.startswith("On branch") or "ahead of" in lower or "behind" in lower:
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
    semantic_result = _reduce_semantic_json_payload(payload, target_bytes=target_bytes)
    if semantic_result is not None:
        return semantic_result
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


def _reduce_semantic_json_payload(payload: Any, *, target_bytes: int) -> ReducerOutput | None:
    semantic_list = _semantic_list(payload)
    if semantic_list is None:
        return None
    list_key, items = semantic_list
    rendered_limit = min(len(items), 12)
    lines: list[str] = ["semantic json payload"]
    facts: dict[str, Any] = {
        "semantic_items": len(items),
        "semantic_items_rendered": rendered_limit,
    }
    if isinstance(payload, dict):
        keys = list(payload.keys())
        lines.append(f"top_level_key_count: {len(keys)}")
        lines.append("top_level_keys: " + ", ".join(str(key) for key in keys[:80]))
        for key in ("status_code", "status", "query", "profile", "app_id", "workspace_id", "message", "detail"):
            if key in payload and not isinstance(payload.get(key), (dict, list)):
                lines.append(f"{key}: {_bounded_text(payload.get(key), 240)}")
    lines.append(f"{list_key}: semantic array length {len(items)}")
    for index, item in enumerate(items[:rendered_limit], start=1):
        summary = _semantic_item_summary(item)
        lines.append(f"{index}. {_bounded_json_bytes(summary, 1_400)}")
    omitted = len(items) - rendered_limit
    if omitted > 0:
        lines.append(f"omitted_semantic_items: {omitted}")
    return ReducerOutput(text=truncate_middle_bytes("\n".join(lines), target_bytes), facts=facts)


def _semantic_list(payload: Any) -> tuple[str, list[Any]] | None:
    if isinstance(payload, dict):
        for key in ("items", "results"):
            value = payload.get(key)
            if _looks_like_semantic_items(value):
                return key, value
    if _looks_like_semantic_items(payload):
        return "root", payload
    return None


def _looks_like_semantic_items(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    candidates = [item for item in value[:8] if isinstance(item, dict)]
    if not candidates:
        return False
    return sum(1 for item in candidates if _looks_like_semantic_item(item)) >= max(1, len(candidates) // 2)


def _looks_like_semantic_item(item: dict[str, Any]) -> bool:
    textish = any(key in item for key in ("title", "summary", "body_text", "snippet", "description"))
    if "kind" in item and (textish or "entity" in item or "locator" in item):
        return True
    if "entity" in item and textish:
        return True
    if "locator" in item and textish:
        return True
    if "node_id" in item and textish:
        return True
    return False


def _semantic_item_summary(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"value": _bounded_text(item, 240)}
    node = item.get("node") if isinstance(item.get("node"), dict) else {}
    body_text = str(item.get("body_text") or node.get("body_text") or "")
    compiled = item.get("compiled") if isinstance(item.get("compiled"), dict) else {}
    summary = _compact_json_dict(
        {
            "kind": item.get("kind"),
            "id": item.get("id") or node.get("id"),
            "node_id": item.get("node_id") or node.get("node_id"),
            "type": item.get("type") or node.get("type"),
            "title": _bounded_text(item.get("title") or node.get("title"), 240),
            "summary": _bounded_text(item.get("summary") or node.get("summary") or body_text, 240),
            "body_text": _bounded_text(body_text, 180),
            "body_text_char_count": len(body_text) if body_text else item.get("body_text_char_count"),
            "freshness": item.get("freshness"),
            "relevance": item.get("relevance"),
            "reason": _bounded_text(item.get("reason"), 160),
            "match_sources": item.get("match_sources"),
            "entity": item.get("entity"),
            "locator": item.get("locator"),
            "source_chunk_matches": _semantic_source_chunks(item.get("source_chunk_matches")),
            "citations": _semantic_citations(item.get("citations")),
            "provenance": _semantic_refs(item.get("provenance")),
            "storage_references": _semantic_storage_refs(item.get("storage_references")),
            "compiled": _semantic_compiled(compiled),
        }
    )
    return summary


def _semantic_compiled(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    body_markdown = str(value.get("body_markdown") or "")
    return _compact_json_dict(
        {
            "wiki_page_id": value.get("wiki_page_id"),
            "summary": _bounded_text(value.get("summary"), 180),
            "body_markdown_char_count": len(body_markdown) if body_markdown else value.get("body_markdown_char_count"),
            "freshness": value.get("freshness"),
            "compiled_at": value.get("compiled_at"),
            "claims": _semantic_claims(value.get("claims")),
            "citations": _semantic_citations(value.get("citations")),
            "storage_references": _semantic_storage_refs(value.get("storage_references")),
            "lint_findings": _semantic_lint_findings(value.get("lint_findings")),
        }
    )


def _semantic_claims(value: Any) -> list[dict[str, Any]]:
    claims = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for claim in claims[:3]:
        if not isinstance(claim, dict):
            continue
        compacted.append(
            _compact_json_dict(
                {
                    "id": claim.get("id"),
                    "claim_id": claim.get("claim_id"),
                    "claim_text": _bounded_text(claim.get("claim_text") or claim.get("summary"), 180),
                    "status": claim.get("status"),
                    "confidence": claim.get("confidence"),
                    "citations": _semantic_citations(claim.get("citations")),
                }
            )
        )
    return compacted


def _semantic_citations(value: Any) -> list[dict[str, Any]]:
    citations = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for citation in citations[:3]:
        if not isinstance(citation, dict):
            continue
        compacted.append(
            _compact_json_dict(
                {
                    "id": citation.get("id"),
                    "claim_id": citation.get("claim_id"),
                    "source_id": citation.get("source_id"),
                    "source_version_id": citation.get("source_version_id"),
                    "source_chunk_id": citation.get("source_chunk_id"),
                    "external_ref_id": citation.get("external_ref_id"),
                    "locator": citation.get("locator"),
                    "locator_kind": citation.get("locator_kind"),
                    "quote": _bounded_text(citation.get("quote"), 120),
                    "quote_sha256": citation.get("quote_sha256"),
                    "storage_reference": _semantic_storage_ref(citation.get("storage_reference")),
                }
            )
        )
    return compacted


def _semantic_source_chunks(value: Any) -> list[dict[str, Any]]:
    chunks = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for chunk in chunks[:3]:
        if not isinstance(chunk, dict):
            continue
        compacted.append(
            _compact_json_dict(
                {
                    "kind": chunk.get("kind"),
                    "source_id": chunk.get("source_id"),
                    "source_document_id": chunk.get("source_document_id"),
                    "source_version_id": chunk.get("source_version_id"),
                    "chunk_id": chunk.get("chunk_id"),
                    "title": _bounded_text(chunk.get("title"), 180),
                    "freshness": chunk.get("freshness"),
                    "locator": chunk.get("locator"),
                    "source": chunk.get("source"),
                    "citations": _semantic_citations(chunk.get("citations")),
                }
            )
        )
    return compacted


def _semantic_refs(value: Any) -> list[dict[str, Any]]:
    refs = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for ref in refs[:3]:
        if not isinstance(ref, dict):
            continue
        metadata = ref.get("metadata") if isinstance(ref.get("metadata"), dict) else {}
        compacted.append(
            _compact_json_dict(
                {
                    "id": ref.get("id"),
                    "ref_kind": ref.get("ref_kind"),
                    "owning_app_id": ref.get("owning_app_id"),
                    "entity_type": ref.get("entity_type"),
                    "entity_id": ref.get("entity_id"),
                    "file_id": ref.get("file_id"),
                    "workspace_relative_path": ref.get("workspace_relative_path"),
                    "uri": ref.get("uri"),
                    "title": _bounded_text(ref.get("title"), 180),
                    "metadata": _compact_json_dict(
                        {
                            "provider": metadata.get("provider"),
                            "connection_id": metadata.get("connection_id"),
                            "drive_file_id": metadata.get("drive_file_id"),
                            "source_version": metadata.get("source_version"),
                            "indexed_source_version": metadata.get("indexed_source_version"),
                        }
                    ),
                }
            )
        )
    return compacted


def _semantic_storage_refs(value: Any) -> list[dict[str, Any]]:
    refs = value if isinstance(value, list) else []
    return [ref for ref in (_semantic_storage_ref(ref) for ref in refs[:3]) if ref]


def _semantic_storage_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compacted = _compact_json_dict(
        {
            "app_id": value.get("app_id"),
            "owning_app_id": value.get("owning_app_id"),
            "entity_type": value.get("entity_type"),
            "provider": value.get("provider"),
            "stable_storage_file_id": value.get("stable_storage_file_id"),
            "file_id": value.get("file_id"),
            "entity_id": value.get("entity_id"),
            "ref_kind": value.get("ref_kind"),
            "title": _bounded_text(value.get("title"), 180),
            "display_path": _bounded_text(value.get("display_path"), 240),
            "connection_id": value.get("connection_id"),
            "drive_file_id": value.get("drive_file_id"),
            "source_version": value.get("source_version"),
            "deep_link": value.get("deep_link"),
            "reference_resolve_request": value.get("reference_resolve_request"),
            "preview_request": value.get("preview_request"),
            "export_request": value.get("export_request"),
        }
    )
    if "workspace_relative_path" in value:
        compacted["workspace_relative_path"] = str(value.get("workspace_relative_path") or "")
    return compacted


def _semantic_lint_findings(value: Any) -> list[dict[str, Any]]:
    findings = value if isinstance(value, list) else []
    compacted: list[dict[str, Any]] = []
    for finding in findings[:2]:
        if not isinstance(finding, dict):
            continue
        compacted.append(
            _compact_json_dict(
                {
                    "id": finding.get("id"),
                    "finding_type": finding.get("finding_type"),
                    "severity": finding.get("severity"),
                    "message": _bounded_text(finding.get("message"), 180),
                }
            )
        )
    return compacted


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
    if stripped.startswith("?? "):
        return "untracked"
    if stripped.startswith("!! "):
        return ""
    porcelain_label = _git_porcelain_status_label(stripped)
    if porcelain_label:
        return porcelain_label
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


def _git_porcelain_status_label(stripped: str) -> str:
    if len(stripped) < 3 or stripped[2] != " ":
        return ""
    codes = stripped[:2]
    valid_codes = set(" MADRCUT?!")
    if any(code not in valid_codes for code in codes):
        return ""
    if "U" in codes or codes in {"AA", "DD"}:
        return "conflicted"
    if "R" in codes:
        return "renamed"
    if "C" in codes:
        return "copied"
    if "A" in codes:
        return "added"
    if "D" in codes:
        return "deleted"
    if "M" in codes or "T" in codes:
        return "modified"
    return ""


def _bounded_text(value: Any, max_chars: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if max_chars <= 0 or not text:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _bounded_json_bytes(value: Any, max_bytes: int) -> str:
    return truncate_middle_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), max_bytes).replace("\n", " ")


def _compact_json_dict(value: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, item in value.items():
        if item is None or item == "" or item == [] or item == {}:
            continue
        compacted[key] = item
    return compacted


def _bounded_json(value: Any) -> str:
    return truncate_middle_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str), 600).replace("\n", " ")


def _sample_list(value: list[Any]) -> list[Any]:
    if len(value) <= 6:
        return value
    return [*value[:3], "...", *value[-3:]]
