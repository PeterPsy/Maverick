"""Runtime-local Codex hook script management."""

from __future__ import annotations

from pathlib import Path


CODEX_POST_TOOL_USE_HOOK_NAME = "maverick_codex_post_tool_use_hook.py"


def write_codex_post_tool_use_hook(path: Path) -> None:
    """Write the runtime-local Codex PostToolUse hook bridge."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_codex_post_tool_use_hook_source(), encoding="utf-8")
    path.chmod(0o755)


def _codex_post_tool_use_hook_source() -> str:
    """Return a standalone hook bridge that can run without importing Maverick."""
    return r'''#!/usr/bin/env python3
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request


API_PATH = "/api/runtime/provider-hooks/codex/post-tool-use"
MIN_FALLBACK_BYTES = 16000
MAX_FALLBACK_BYTES = 12000
SENSITIVE_QUERY_KEYS = "token|access_token|refresh_token|api_key|key|secret|password|code"


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    response = call_maverick(payload)
    if isinstance(response, dict):
        if response.get("emit") and isinstance(response.get("response"), dict):
            print(json.dumps(response["response"], separators=(",", ":")))
        return 0

    fallback = fallback_response(payload)
    if fallback is not None:
        print(json.dumps(fallback, separators=(",", ":")))
    return 0


def call_maverick(payload):
    token = os.environ.get("MAVERICK_RUNTIME_API_TOKEN", "").strip()
    if not token:
        return None
    base_url = os.environ.get("MAVERICK_API_BASE", "http://127.0.0.1:8014").rstrip("/")
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
        return None
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def fallback_response(payload):
    if compaction_disabled():
        return None
    if str(payload.get("hook_event_name") or payload.get("hookEventName") or "") != "PostToolUse":
        return None
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    if tool_name.lower() not in {"bash", "shell", "shell_command", "local_shell"}:
        return None
    text = extract_response_text(payload)
    if not text:
        return None
    original_bytes = byte_len(text)
    redacted = redact_text(text)
    if original_bytes < MIN_FALLBACK_BYTES and redacted == text:
        return None
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
    return {"decision": "block", "continue": False, "reason": header + "\n\n" + compacted}


def compaction_disabled():
    value = os.environ.get("MAVERICK_RUNTIME_OUTPUT_COMPACTION", "1").strip().lower()
    return value in {"0", "false", "no", "off", "disabled"}


def extract_response_text(payload):
    response = payload.get("tool_response") if "tool_response" in payload else payload.get("toolResponse")
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
        (r"(?i)(Authorization:\s*Bearer\s+)[^\s]+", r"\1<redacted>"),
        (r"(?i)(Authorization:\s*Basic\s+)[^\s]+", r"\1<redacted>"),
        (r"(?im)^(Cookie|Set-Cookie):.*$", r"\1: <redacted>"),
        (r"(?im)^([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|KEY)[A-Z0-9_]*\s*=\s*).+$", r"\1<redacted>"),
        (r"([?&](?:" + SENSITIVE_QUERY_KEYS + r")=)[^&\s]+", r"\1<redacted>"),
        (r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "<redacted-jwt>"),
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "<redacted-private-key>"),
    )
    redacted = text
    for pattern, replacement in replacements:
        try:
            redacted = re.sub(pattern, replacement, redacted, flags=re.DOTALL if "PRIVATE KEY" in pattern else 0)
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
