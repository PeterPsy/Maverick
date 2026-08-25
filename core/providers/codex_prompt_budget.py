"""Lean explicit-thread prompt profile and exact first-turn budget telemetry."""

from __future__ import annotations

from typing import Any


CODEX_EXPLICIT_PROMPT_PROFILE = "maverick-explicit-lean-v1"
CODEX_EXPLICIT_FIRST_TURN_INPUT_TOKEN_BUDGET = 8_000
CODEX_EXPLICIT_PROJECT_DOC_MAX_BYTES = 2_048
CODEX_EXPLICIT_BASE_INSTRUCTIONS = (
    "You are Maverick's agentic runtime assistant. Follow developer and user instructions in priority order. "
    "Use available tools only when helpful, respect their schemas, and stay within the configured workspace and "
    "approval policy. Preserve unrelated user changes and avoid destructive actions unless explicitly requested. "
    "Before changing repository code, read every applicable AGENTS.md in full with the available tools because "
    "its automatically supplied excerpt may be truncated. Skills are active only when Maverick supplies a "
    "structured skill item for the current turn; do not infer activation from textual dollar markers. Read "
    "supplied skill instructions before using that skill. Give concise progress updates and a self-contained "
    "final answer."
)


def configure_codex_prompt_budget(runtime: Any, session: Any) -> None:
    if runtime.prompt_budget_configured:
        return
    runtime.prompt_budget_configured = True
    if getattr(session, "skill_activation_mode", "implicit") != "explicit":
        return
    runtime.prompt_profile = CODEX_EXPLICIT_PROMPT_PROFILE
    runtime.first_turn_input_token_budget = CODEX_EXPLICIT_FIRST_TURN_INPUT_TOKEN_BUDGET
    runtime.prompt_budget_pending = not bool(
        str(getattr(session, "provider_thread_id", "") or "").strip()
    )


def add_first_turn_prompt_budget(
    runtime: Any,
    payload: dict[str, Any],
    *,
    provider_turn_id: str,
    latest_input_tokens: int,
    latest_cached_input_tokens: int,
    final_snapshot: bool,
) -> None:
    if not getattr(runtime, "prompt_budget_pending", False):
        return
    budget = getattr(runtime, "first_turn_input_token_budget", None)
    profile = str(getattr(runtime, "prompt_profile", "") or "").strip()
    if not isinstance(budget, int) or budget <= 0 or not profile:
        return
    budget_turn_id = str(getattr(runtime, "prompt_budget_turn_id", "") or "").strip()
    if not budget_turn_id:
        runtime.prompt_budget_turn_id = provider_turn_id
        budget_turn_id = provider_turn_id
    if provider_turn_id != budget_turn_id:
        return
    runtime.prompt_budget_latest_input_tokens = latest_input_tokens
    runtime.prompt_budget_latest_cached_input_tokens = latest_cached_input_tokens
    non_cached_input_tokens = max(0, latest_input_tokens - latest_cached_input_tokens)
    payload.update(
        {
            "prompt_profile": profile,
            "first_turn_input_token_budget": budget,
            "latest_non_cached_input_tokens": non_cached_input_tokens,
            "first_turn_within_input_budget": non_cached_input_tokens <= budget,
            "prompt_budget_final": final_snapshot,
        }
    )


def final_prompt_budget_payload(runtime: Any) -> dict[str, Any] | None:
    if not getattr(runtime, "prompt_budget_pending", False):
        return None
    budget = getattr(runtime, "first_turn_input_token_budget", None)
    input_tokens = getattr(runtime, "prompt_budget_latest_input_tokens", None)
    cached_tokens = getattr(runtime, "prompt_budget_latest_cached_input_tokens", None)
    profile = str(getattr(runtime, "prompt_profile", "") or "").strip()
    provider_turn_id = str(getattr(runtime, "prompt_budget_turn_id", "") or "").strip()
    if not all(
        (
            isinstance(budget, int) and budget > 0,
            isinstance(input_tokens, int) and input_tokens >= 0,
            isinstance(cached_tokens, int) and cached_tokens >= 0,
            bool(profile),
            bool(provider_turn_id),
        )
    ):
        return None
    non_cached_input_tokens = max(0, input_tokens - cached_tokens)
    return {
        "provider_id": "codex",
        "source": "codex_app_server",
        "token_accuracy": "exact",
        "prompt_profile": profile,
        "first_turn_input_token_budget": budget,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "non_cached_input_tokens": non_cached_input_tokens,
        "within_budget": non_cached_input_tokens <= budget,
        "provider_thread_id": str(getattr(runtime, "provider_thread_id", "") or "").strip() or None,
        "provider_turn_id": provider_turn_id,
    }
