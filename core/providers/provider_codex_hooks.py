"""Runtime-local Codex hook script management."""

from __future__ import annotations

from pathlib import Path

from core.runtime.output_compaction.redaction import (
    KNOWN_UNDERSCORE_TOKEN_PREFIX_PATTERN,
    SENSITIVE_QUERY_KEY_PATTERN,
)


CODEX_POST_TOOL_USE_HOOK_NAME = "maverick_codex_post_tool_use_hook.py"


def write_codex_post_tool_use_hook(path: Path) -> None:
    """Write the runtime-local Codex PostToolUse hook bridge."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_codex_post_tool_use_hook_source(), encoding="utf-8")
    path.chmod(0o755)


def _codex_post_tool_use_hook_source() -> str:
    """Return a standalone hook bridge that can run without importing Maverick."""
    source = r'''#!/usr/bin/env python3
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request


API_PATH = "/api/runtime/provider-hooks/codex/post-tool-use"
DIAGNOSTIC_LOG_RELATIVE_PATH = os.path.join("logs", "provider-hook-events.jsonl")
MIN_FALLBACK_BYTES = 16000
MAX_FALLBACK_BYTES = 12000
SENSITIVE_QUERY_KEYS = "__MAVERICK_SENSITIVE_QUERY_KEYS__"
KNOWN_UNDERSCORE_TOKEN_PREFIXES = "__MAVERICK_KNOWN_UNDERSCORE_TOKEN_PREFIXES__"


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        write_hook_diagnostic({}, bridge_status="called", fallback_status="invalid_payload")
        return 0
    if not isinstance(payload, dict):
        write_hook_diagnostic({}, bridge_status="called", fallback_status="invalid_payload")
        return 0

    write_hook_diagnostic(payload, bridge_status="called", fallback_status="not_run")
    response, bridge_status = call_maverick(payload)
    if isinstance(response, dict):
        if response.get("emit") and isinstance(response.get("response"), dict):
            write_hook_diagnostic(payload, bridge_status=bridge_status, fallback_status="not_run")
            print(json.dumps(response["response"], separators=(",", ":")))
        else:
            write_hook_diagnostic(payload, bridge_status=bridge_status, fallback_status="not_run")
        return 0

    fallback = fallback_response(payload, bridge_status=bridge_status)
    if fallback is not None:
        print(json.dumps(fallback, separators=(",", ":")))
    return 0


def call_maverick(payload):
    token = os.environ.get("MAVERICK_RUNTIME_API_TOKEN", "").strip()
    if not token:
        return None, "unavailable"
    base_url = (os.environ.get("MAVERICK_API_BASE", "").strip() or "http://127.0.0.1:8014").rstrip("/")
    request = urllib.request.Request(
        base_url + API_PATH,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None, "unavailable"
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return None, "unavailable"
    if not isinstance(decoded, dict):
        return None, "unavailable"
    if decoded.get("emit") and isinstance(decoded.get("response"), dict):
        return decoded, "returned_emit"
    return decoded, "returned_no_emit"


def fallback_response(payload, bridge_status="unavailable"):
    response, fallback_status = fallback_response_with_status(payload)
    write_hook_diagnostic(payload, bridge_status=bridge_status, fallback_status=fallback_status)
    return response


def fallback_response_with_status(payload):
    if compaction_disabled():
        return None, "disabled"
    if str(payload.get("hook_event_name") or payload.get("hookEventName") or "") != "PostToolUse":
        return None, "not_post_tool_use"
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    if tool_name.lower() not in {"bash", "shell", "shell_command", "local_shell", "exec_command"}:
        return None, "unsupported_tool"
    text = extract_response_text(payload)
    if not text:
        return None, "no_text"
    original_bytes = byte_len(text)
    redacted = redact_text(text)
    if original_bytes < MIN_FALLBACK_BYTES and redacted == text:
        return None, "below_threshold"
    compacted = bounded_middle(redacted, MAX_FALLBACK_BYTES)
    digest = hashlib.sha256(redacted.encode("utf-8", errors="replace")).hexdigest()
    header = "\n".join(
        [
            "[tool output compacted]",
            "scope: provider_history_tool_result",
            "rule: generic/fallback",
            "pass_through_reason: hook_bridge_unavailable",
            "original_bytes: " + str(original_bytes),
            "redacted_bytes: " + str(byte_len(redacted)),
            "compacted_bytes: " + str(byte_len(compacted)),
            "redacted_sha256: " + digest,
        ]
    )
    return {"decision": "block", "continue": False, "reason": header + "\n\n" + compacted}, "emitted"


def write_hook_diagnostic(payload, bridge_status, fallback_status):
    event = build_hook_diagnostic(
        payload if isinstance(payload, dict) else {},
        bridge_status=bridge_status,
        fallback_status=fallback_status,
    )
    line = json.dumps(event, separators=(",", ":"), sort_keys=True)
    runtime_root = os.environ.get("MAVERICK_RUNTIME_ROOT", "").strip()
    if runtime_root:
        try:
            log_path = os.path.join(runtime_root, DIAGNOSTIC_LOG_RELATIVE_PATH)
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            return
        except OSError:
            pass
    print(line, file=sys.stderr)


def build_hook_diagnostic(payload, bridge_status, fallback_status):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "hook_event_name": diagnostic_string(payload.get("hook_event_name") or payload.get("hookEventName")),
        "tool_name": diagnostic_string(payload.get("tool_name") or payload.get("toolName")),
        "has_token": bool(os.environ.get("MAVERICK_RUNTIME_API_TOKEN", "").strip()),
        "api_base_present": bool(os.environ.get("MAVERICK_API_BASE", "").strip()),
        "compaction_disabled": compaction_disabled(),
        "payload_shape": {"top_level_keys": diagnostic_payload_keys(payload)},
        "extracted_text_bytes": diagnostic_extracted_text_bytes(payload),
        "bridge_status": diagnostic_string(bridge_status),
        "fallback_status": diagnostic_string(fallback_status),
    }


def diagnostic_payload_keys(payload):
    keys = [diagnostic_string(key) for key in payload.keys()]
    return sorted(key for key in keys if key)[:64]


def diagnostic_extracted_text_bytes(payload):
    try:
        return byte_len(extract_response_text(payload))
    except Exception:
        return 0


def diagnostic_string(value):
    if not isinstance(value, str):
        return ""
    collapsed = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return collapsed[:100]


def compaction_disabled():
    value = os.environ.get("MAVERICK_RUNTIME_OUTPUT_COMPACTION", "1").strip().lower()
    return value in {"0", "false", "no", "off", "disabled"}


def extract_response_text(payload):
    response = first_present(payload, ("tool_response", "toolResponse", "tool_result", "toolResult", "result", "response"))
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        output = first_text(response, ("output", "aggregated_output", "aggregatedOutput", "text", "content", "result"))
        stdout = first_text(response, ("stdout",))
        stderr = first_text(response, ("stderr",))
        parts = []
        if output:
            parts.append(output)
        if stdout:
            parts.append("stdout:\n" + stdout)
        if stderr:
            parts.append("stderr:\n" + stderr)
        if parts:
            return "\n\n".join(parts)
        nested = response.get("content") or response.get("messages") or response.get("items")
        return joined_text_fragments(nested)
    if isinstance(response, list):
        return joined_text_fragments(response)
    return ""


def first_present(value, keys):
    for key in keys:
        if key in value:
            return value.get(key)
    return None


def first_text(value, keys):
    for key in keys:
        item = value.get(key)
        if isinstance(item, str):
            return item
    return ""


def joined_text_fragments(value):
    fragments = []

    def visit(item):
        if isinstance(item, str):
            if item:
                fragments.append(item)
            return
        if isinstance(item, dict):
            for key in ("text", "content", "message", "output"):
                child = item.get(key)
                if isinstance(child, str) and child:
                    fragments.append(child)
                    return
            return
        if isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return "\n".join(fragments)


def redact_text(text):
    replacements = (
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "<redacted-private-key>", re.IGNORECASE | re.DOTALL),
        (r"(?i)(Authorization:\s*Bearer\s+)[^\s]+", r"\1<redacted>"),
        (r"(?i)(Authorization:\s*Basic\s+)[^\s]+", r"\1<redacted>"),
        (r"(?im)^(Cookie|Set-Cookie):.*$", r"\1: <redacted>"),
        (r"(?im)^([A-Z0-9_-]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API[-_]?KEY|PRIVATE[-_]?KEY|ACCESS[-_]?KEY)[A-Z0-9_-]*\s*:\s*)[^\r\n]+", r"\1<redacted>"),
        (r"(?im)^([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY|AUTH|KEY)[A-Z0-9_]*\s*=\s*)[^\s#]+", r"\1<redacted>"),
        (r"(?i)([?&](?:" + SENSITIVE_QUERY_KEYS + r")=)[^&#\s]+", r"\1<redacted>"),
        (r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "<redacted-jwt>"),
        (r"(?i)([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@", r"\1<redacted>@"),
        (r"\b(?:" + KNOWN_UNDERSCORE_TOKEN_PREFIXES + r")_[A-Za-z0-9_=-]{16,}\b", "<redacted-key>"),
        (r"\bsk-[A-Za-z0-9_-]{16,}\b", "<redacted-key>"),
    )
    redacted = text
    for item in replacements:
        if len(item) == 3:
            pattern, replacement, flags = item
        else:
            pattern, replacement = item
            flags = 0
        try:
            redacted = re.sub(pattern, replacement, redacted, flags=flags)
        except re.error:
            continue
    return redacted


def bounded_middle(value, max_bytes):
    if byte_len(value) <= max_bytes:
        return value
    marker = "\n... [provider hook fallback compacted] ...\n"
    marker_bytes = byte_len(marker)
    if marker_bytes >= max_bytes:
        return marker.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
    budget = max_bytes - marker_bytes
    head_bytes = budget // 2
    tail_bytes = budget - head_bytes
    encoded = value.encode("utf-8", errors="replace")
    head = encoded[:head_bytes].decode("utf-8", errors="ignore")
    tail = encoded[-tail_bytes:].decode("utf-8", errors="ignore")
    return head + marker + tail


def byte_len(value):
    return len(str(value).encode("utf-8", errors="replace"))


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return (
        source.replace("__MAVERICK_SENSITIVE_QUERY_KEYS__", SENSITIVE_QUERY_KEY_PATTERN)
        .replace("__MAVERICK_KNOWN_UNDERSCORE_TOKEN_PREFIXES__", KNOWN_UNDERSCORE_TOKEN_PREFIX_PATTERN)
    )
