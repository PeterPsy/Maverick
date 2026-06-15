"""Provider-hook adapters for pre-history tool-result compaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import shlex
from typing import Any

from core.runtime.output_compaction.fallbacks import compactor_error_result
from core.runtime.output_compaction.models import (
    ToolOutputCompactionInput,
    ToolOutputCompactionPolicy,
    ToolOutputCompactionResult,
)
from core.runtime.output_compaction.results import savings_ratio
from core.runtime.output_compaction.service import compact_tool_output


PROVIDER_HISTORY_TOOL_RESULT_SCOPE = "provider_history_tool_result"
PROVIDER_HISTORY_COMPACTION_VERSION = 1
CODEX_POST_TOOL_USE_EVENT = "PostToolUse"
SUPPORTED_CODEX_SHELL_TOOLS = frozenset({"bash", "shell", "shell_command", "local_shell"})


def provider_history_compact_policy(base_policy: ToolOutputCompactionPolicy | None = None) -> ToolOutputCompactionPolicy:
    """Return the policy used for output about to enter provider history."""
    policy = base_policy or ToolOutputCompactionPolicy.from_environment()
    return ToolOutputCompactionPolicy(
        enabled=policy.enabled,
        min_original_bytes=min(policy.min_original_bytes, 16_000),
        success_min_savings_ratio=min(policy.success_min_savings_ratio, 0.70),
        failure_min_savings_ratio=min(policy.failure_min_savings_ratio, 0.50),
        target_max_compacted_bytes=min(policy.target_max_compacted_bytes, 10_000),
        failure_target_max_compacted_bytes=min(policy.failure_target_max_compacted_bytes, 16_000),
        failure_tail_lines=policy.failure_tail_lines,
        sanitize_raw_payload=False,
        store_original_artifact=False,
    )


def build_codex_post_tool_use_response(
    hook_payload: Mapping[str, Any],
    *,
    runtime_session_id: str,
    policy: ToolOutputCompactionPolicy | None = None,
) -> dict[str, Any]:
    """Build a Codex PostToolUse hook response for provider-history compaction."""
    if not _is_codex_post_tool_use_shell_payload(hook_payload):
        return {"emit": False}

    extracted = _extract_codex_shell_payload(hook_payload)
    if not extracted.has_text:
        return {"emit": False}

    active_policy = provider_history_compact_policy(policy)
    if not active_policy.enabled:
        return {"emit": False}

    compaction_input = extracted.to_compaction_input(runtime_session_id=runtime_session_id)
    try:
        result = compact_tool_output(compaction_input, policy=active_policy)
    except Exception as error:
        result = compactor_error_result(compaction_input, policy=active_policy, error=error)

    if not _should_replace_provider_result(result, extracted):
        return {
            "emit": False,
            "output_compaction": _provider_hook_metadata(result, tool_name=extracted.tool_name),
        }

    replacement = _replacement_text(result)
    if not replacement:
        return {"emit": False}
    response = {
        "decision": "block",
        "continue": False,
        "reason": replacement,
    }
    return {
        "emit": True,
        "response": response,
        "output_compaction": _provider_hook_metadata(result, tool_name=extracted.tool_name),
    }


class _ExtractedCodexShellPayload:
    def __init__(
        self,
        *,
        hook_event_name: str,
        tool_name: str,
        tool_use_id: str | None,
        command: str | None,
        output: str | None,
        stdout: str | None,
        stderr: str | None,
        exit_code: int | None,
    ) -> None:
        self.hook_event_name = hook_event_name
        self.tool_name = tool_name
        self.tool_use_id = tool_use_id
        self.command = command
        self.output = output
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code

    @property
    def has_text(self) -> bool:
        return any(isinstance(value, str) and value for value in (self.output, self.stdout, self.stderr))

    def to_compaction_input(self, *, runtime_session_id: str) -> ToolOutputCompactionInput:
        status = "failed" if isinstance(self.exit_code, int) and self.exit_code != 0 else "completed"
        return ToolOutputCompactionInput(
            provider_id="codex",
            provider_event_type=f"codex.{self.hook_event_name}",
            runtime_session_id=runtime_session_id,
            turn_id=None,
            event_type="provider.tool_hook.post_tool_use",
            tool_call_id=self.tool_use_id,
            tool_name=self.tool_name,
            tool_kind="shell",
            command=self.command,
            argv=_argv_from_command(self.command),
            cwd=None,
            output=self.output,
            stdout=self.stdout,
            stderr=self.stderr,
            exit_code=self.exit_code,
            raw=None,
            metadata={
                "status": status,
                "compaction_scope": PROVIDER_HISTORY_TOOL_RESULT_SCOPE,
                "provider_hook": "codex.PostToolUse",
            },
        )


def _is_codex_post_tool_use_shell_payload(payload: Mapping[str, Any]) -> bool:
    hook_event_name = _optional_string(payload.get("hook_event_name") or payload.get("hookEventName"))
    if hook_event_name != CODEX_POST_TOOL_USE_EVENT:
        return False
    tool_name = _optional_string(payload.get("tool_name") or payload.get("toolName"))
    return _normalized_tool_name(tool_name) in SUPPORTED_CODEX_SHELL_TOOLS


def _extract_codex_shell_payload(payload: Mapping[str, Any]) -> _ExtractedCodexShellPayload:
    hook_event_name = _optional_string(payload.get("hook_event_name") or payload.get("hookEventName")) or CODEX_POST_TOOL_USE_EVENT
    tool_name = _optional_string(payload.get("tool_name") or payload.get("toolName")) or "Bash"
    tool_use_id = _optional_string(payload.get("tool_use_id") or payload.get("toolUseId"))
    tool_input = _mapping(payload.get("tool_input") or payload.get("toolInput"))
    tool_response = payload.get("tool_response") if "tool_response" in payload else payload.get("toolResponse")
    response = _response_text_fields(tool_response)
    return _ExtractedCodexShellPayload(
        hook_event_name=hook_event_name,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        command=_optional_string(tool_input.get("command")),
        output=response["output"],
        stdout=response["stdout"],
        stderr=response["stderr"],
        exit_code=response["exit_code"],
    )


def _response_text_fields(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"output": value, "stdout": None, "stderr": None, "exit_code": None}
    if isinstance(value, Mapping):
        stdout = _optional_string(value.get("stdout"), allow_empty=True)
        stderr = _optional_string(value.get("stderr"), allow_empty=True)
        output = _first_text(
            value,
            (
                "output",
                "aggregated_output",
                "aggregatedOutput",
                "text",
                "content",
                "result",
            ),
        )
        if output is None and stdout is None and stderr is None:
            output = _joined_text_fragments(value.get("content") or value.get("messages") or value.get("items"))
        return {
            "output": output,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": _exit_code(value),
        }
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return {"output": _joined_text_fragments(value), "stdout": None, "stderr": None, "exit_code": None}
    return {"output": None, "stdout": None, "stderr": None, "exit_code": None}


def _joined_text_fragments(value: Any) -> str | None:
    fragments: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            if item:
                fragments.append(item)
            return
        if isinstance(item, Mapping):
            for key in ("text", "content", "message", "output"):
                child = item.get(key)
                if isinstance(child, str) and child:
                    fragments.append(child)
                    return
            return
        if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray)):
            for child in item:
                visit(child)

    visit(value)
    text = "\n".join(fragments).strip()
    return text or None


def _first_text(value: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        text = _optional_string(value.get(key), allow_empty=True)
        if text is not None:
            return text
    return None


def _exit_code(value: Mapping[str, Any]) -> int | None:
    for key in ("exit_code", "exitCode", "returncode", "returnCode"):
        candidate = value.get(key)
        if isinstance(candidate, int):
            return candidate
    return None


def _should_replace_provider_result(result: ToolOutputCompactionResult, extracted: _ExtractedCodexShellPayload) -> bool:
    if result.applied or result.redaction_failed or result.compaction_error:
        return True
    return (
        result.output != extracted.output
        or result.stdout != extracted.stdout
        or result.stderr != extracted.stderr
    )


def _replacement_text(result: ToolOutputCompactionResult) -> str:
    if isinstance(result.output, str) and result.output:
        return result.output
    parts: list[str] = []
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr}")
    return "\n\n".join(parts).strip()


def _provider_hook_metadata(result: ToolOutputCompactionResult, *, tool_name: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "version": PROVIDER_HISTORY_COMPACTION_VERSION,
        "scope": PROVIDER_HISTORY_TOOL_RESULT_SCOPE,
        "provider_hook": "codex.PostToolUse",
        "tool_name": tool_name,
        "applied": result.applied,
        "rule_id": result.rule_id,
        "family": result.family,
        "original_bytes": result.original_bytes,
        "redacted_bytes": result.redacted_bytes,
        "compacted_bytes": result.compacted_bytes,
        "savings_ratio": round(savings_ratio(result.original_bytes, result.compacted_bytes), 6),
        "required_savings_ratio": result.required_savings_ratio,
        "target_max_compacted_bytes": result.target_max_compacted_bytes,
        "redacted": result.redacted,
        "digest_kind": "redacted_sha256",
        "digest": result.redacted_sha256,
        "fields": list(result.fields),
        "pass_through_reason": result.pass_through_reason,
    }
    if result.redaction_failed:
        metadata["redaction_failed"] = True
    if result.compaction_error:
        metadata["compaction_error"] = result.compaction_error
    if result.facts:
        metadata["facts"] = dict(result.facts)
    return metadata


def _normalized_tool_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _argv_from_command(command: str | None) -> tuple[str, ...]:
    if not command:
        return ()
    try:
        return tuple(shlex.split(command))
    except ValueError:
        return tuple(command.split())


def _optional_string(value: Any, *, allow_empty: bool = False) -> str | None:
    if isinstance(value, str) and (allow_empty or value.strip()):
        return value
    return None
