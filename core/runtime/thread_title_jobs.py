"""Asynchronous AI-backed runtime thread title generation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import hashlib
import json
import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any

from core.providers.errors import ProviderError
from core.providers.service import resolve_provider_for_workspace
from core.runtime.runtime_threads import complete_runtime_thread_title_generation
from core.runtime.thread_title_generation import DEFAULT_THREAD_TITLE, MAX_THREAD_TITLE_CHARS, derive_thread_title

if TYPE_CHECKING:
    from core.api.platform_state import PlatformState
    from core.runtime.runtime_thread import RuntimeThreadRecord


MIN_AI_THREAD_TITLE_WORDS = 4
MAX_AI_THREAD_TITLE_WORDS = 8
_DEFAULT_TITLE_TIMEOUT_SECONDS = 20
_TITLE_PROCESS_SHUTDOWN_SECONDS = 1.0
_TITLE_TOKEN = re.compile(r"[^\W_]+(?:[.+][^\W_]+)*", re.UNICODE)

ThreadTitleGenerator = Callable[..., str]


class ThreadTitleGenerationError(RuntimeError):
    """Raised when the AI title generator cannot produce a valid title."""


def thread_title_input_hash(
    input_text: object,
    *,
    attachments: Iterable[Mapping[str, object]] | None = None,
    app_references: Iterable[Mapping[str, object]] | None = None,
) -> str:
    """Return a stable hash for one title-generation input."""
    payload = {
        "input_text": str(input_text or "").strip(),
        "attachments": _stable_items(attachments),
        "app_references": _stable_items(app_references),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def schedule_runtime_thread_title_generation(
    state: "PlatformState",
    *,
    thread: "RuntimeThreadRecord | None",
    input_text: object,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    title_generator: ThreadTitleGenerator | None = None,
) -> None:
    """Start a best-effort background title-generation job for one pending thread."""
    if thread is None or not thread.title_pending:
        return
    if getattr(state, "runtime_thread_event_bus", None) is None:
        return
    input_hash = thread.title_generation_input_hash or thread_title_input_hash(
        input_text,
        attachments=attachments,
        app_references=app_references,
    )
    worker = Thread(
        target=run_runtime_thread_title_generation,
        kwargs={
            "state": state,
            "workspace_id": thread.workspace_id,
            "runtime_session_id": thread.runtime_session_id,
            "title_generation_input_hash": input_hash,
            "input_text": input_text,
            "attachments": attachments,
            "app_references": app_references,
            "title_generator": title_generator,
        },
        daemon=True,
        name=f"maverick-thread-title-{thread.thread_id}",
    )
    worker.start()


def run_runtime_thread_title_generation(
    *,
    state: "PlatformState",
    workspace_id: str,
    runtime_session_id: str,
    title_generation_input_hash: str,
    input_text: object,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
    title_generator: ThreadTitleGenerator | None = None,
) -> "RuntimeThreadRecord | None":
    """Generate and persist a title for one pending runtime thread."""
    source = "ai"
    failure = None
    try:
        generator = title_generator or generate_ai_thread_title
        title = normalize_ai_thread_title(
            generator(
                state=state,
                workspace_id=workspace_id,
                input_text=input_text,
                attachments=attachments,
                app_references=app_references,
            )
        )
    except Exception as error:
        source = "deterministic"
        failure = str(error)[:240]
        title = fallback_thread_title(input_text, attachments=attachments, app_references=app_references)

    updated = complete_runtime_thread_title_generation(
        state.runtime_store,
        workspace_id=workspace_id,
        runtime_session_id=runtime_session_id,
        title_generation_input_hash=title_generation_input_hash,
        title=title,
        title_source=source,
        failure=failure,
    )
    if updated is not None and not updated.title_pending:
        from core.runtime.thread_catalog_events import publish_runtime_thread_catalog_change

        publish_runtime_thread_catalog_change(
            state,
            workspace_id=workspace_id,
            action="updated",
            thread=updated,
        )
    return updated


def generate_ai_thread_title(
    *,
    state: "PlatformState",
    workspace_id: str,
    input_text: object,
    attachments: list[dict[str, object]] | None = None,
    app_references: list[dict[str, object]] | None = None,
) -> str:
    """Generate one thread title through the configured Codex model."""
    model_id, reasoning_effort = _codex_model_settings(state, workspace_id=workspace_id)
    prompt = _title_prompt(input_text=input_text, attachments=attachments, app_references=app_references)
    timeout_seconds = _title_timeout_seconds()
    command = _codex_title_command(
        repository_root=state.repository_root,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
    )
    with tempfile.TemporaryDirectory(prefix="maverick-title-") as temp_dir:
        temp_root = Path(temp_dir)
        schema_path = temp_root / "schema.json"
        output_path = temp_root / "title.json"
        schema_path.write_text(json.dumps(_title_output_schema(), separators=(",", ":")), encoding="utf-8")
        command.extend(["--output-schema", str(schema_path), "-o", str(output_path), "-"])
        result = _run_codex_title_command(command, prompt=prompt, timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Codex title generation failed.").strip()
            raise ThreadTitleGenerationError(detail[:240])
        if not output_path.exists():
            raise ThreadTitleGenerationError("Codex title generation did not produce output.")
        payload = _json_object(output_path.read_text(encoding="utf-8"))
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ThreadTitleGenerationError("Codex title generation returned an empty title.")
    return title


def _run_codex_title_command(
    command: list[str],
    *,
    prompt: str,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        raise ThreadTitleGenerationError(str(error)) from error
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        _terminate_title_process_group(process)
        raise ThreadTitleGenerationError(f"Codex title generation timed out after {timeout_seconds} seconds.") from error
    except subprocess.SubprocessError as error:
        _terminate_title_process_group(process)
        raise ThreadTitleGenerationError(str(error)) from error
    return subprocess.CompletedProcess(command, process.returncode or 0, stdout or "", stderr or "")


def _terminate_title_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    _signal_title_process_group(process, signal.SIGTERM)
    try:
        process.wait(timeout=_TITLE_PROCESS_SHUTDOWN_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    _signal_title_process_group(process, signal.SIGKILL)
    try:
        process.wait(timeout=_TITLE_PROCESS_SHUTDOWN_SECONDS)
    except subprocess.TimeoutExpired:
        return


def _signal_title_process_group(process: subprocess.Popen[str], signum: int) -> None:
    try:
        os.killpg(process.pid, signum)
    except Exception:
        try:
            if signum == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except Exception:
            return


def normalize_ai_thread_title(value: object) -> str:
    """Validate and normalize one AI-produced title."""
    title = str(value or "").strip()
    title = title.strip("`'\" \t\r\n")
    title = re.sub(r"\s+", " ", title).strip(" .,:;!?")
    if not title or "\n" in title or "{" in title or "}" in title:
        raise ThreadTitleGenerationError("invalid_title_shape")
    tokens = _TITLE_TOKEN.findall(title)
    if len(tokens) < MIN_AI_THREAD_TITLE_WORDS:
        raise ThreadTitleGenerationError("title_too_short")
    if len(tokens) > MAX_AI_THREAD_TITLE_WORDS:
        title = _trim_to_word_limit(title, MAX_AI_THREAD_TITLE_WORDS)
    return _bounded_title(title)


def fallback_thread_title(
    input_text: object,
    *,
    attachments: Iterable[Mapping[str, object]] | None = None,
    app_references: Iterable[Mapping[str, object]] | None = None,
) -> str:
    """Return a deterministic, bounded fallback title."""
    title = derive_thread_title(input_text, attachments=attachments, app_references=app_references)
    words = _TITLE_TOKEN.findall(title if title != DEFAULT_THREAD_TITLE else "")
    if len(words) >= MIN_AI_THREAD_TITLE_WORDS:
        return _bounded_title(_trim_to_word_limit(title, MAX_AI_THREAD_TITLE_WORDS))
    for word in _context_words(input_text=input_text, attachments=attachments, app_references=app_references):
        if len(words) >= MIN_AI_THREAD_TITLE_WORDS:
            break
        if _word_key(word) not in {_word_key(item) for item in words}:
            words.append(word)
    suffix = _fallback_suffix(attachments=attachments, app_references=app_references)
    for word in suffix:
        if len(words) >= MIN_AI_THREAD_TITLE_WORDS:
            break
        if _word_key(word) not in {_word_key(item) for item in words}:
            words.append(word)
    if len(words) < MIN_AI_THREAD_TITLE_WORDS:
        words = ["Primo", "Messaggio", "Chat", "Maverick"]
    return _bounded_title(" ".join(words[:MAX_AI_THREAD_TITLE_WORDS]))


def _codex_model_settings(state: "PlatformState", *, workspace_id: str) -> tuple[str, str | None]:
    try:
        definition, selection = resolve_provider_for_workspace(state.provider_store, workspace_id=workspace_id)
    except ProviderError as error:
        raise ThreadTitleGenerationError(str(error)) from error
    if definition.provider_id != "codex":
        raise ThreadTitleGenerationError(f"Provider `{definition.provider_id}` does not support title micro-tasks.")
    model_id = (None if selection is None else selection.model_id) or definition.default_model_family or "gpt-5.5"
    option = next((item for item in definition.model_options if item.model_id == model_id), None)
    supported = {item.effort for item in option.supported_reasoning_efforts} if option is not None else set()
    if "low" in supported:
        return model_id, "low"
    if option is not None and option.default_reasoning_effort:
        return model_id, option.default_reasoning_effort
    return model_id, None if selection is None else selection.model_reasoning_effort


def _codex_title_command(*, repository_root: Path, model_id: str, reasoning_effort: str | None) -> list[str]:
    command = [
        os.environ.get("MAVERICK_CODEX_COMMAND", "").strip() or "codex",
        "exec",
        "--ephemeral",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
        "--skip-git-repo-check",
        "-C",
        str(repository_root),
        "-m",
        model_id,
    ]
    if reasoning_effort:
        command.extend(["-c", f"model_reasoning_effort={reasoning_effort!r}"])
    return command


def _title_prompt(
    *,
    input_text: object,
    attachments: list[dict[str, object]] | None,
    app_references: list[dict[str, object]] | None,
) -> str:
    context = {
        "first_user_message": str(input_text or "").strip(),
        "attachments": _stable_items(attachments),
        "app_references": _stable_items(app_references),
    }
    return (
        "You generate only concise Maverick chat thread titles.\n"
        "Return a JSON object matching the schema exactly.\n"
        "Title rules: use the same language as the user message; use 4 to 8 words; "
        "describe the concrete topic; do not use quotes, trailing punctuation, emojis, "
        "or generic words like request/user/chat unless they are the actual topic.\n"
        "Use only the first user message, attachment labels, and app reference labels. "
        "Do not answer the message.\n\n"
        f"Context JSON:\n{json.dumps(context, ensure_ascii=False, sort_keys=True)}"
    )


def _title_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_THREAD_TITLE_CHARS,
            }
        },
        "required": ["title"],
    }


def _title_timeout_seconds() -> int:
    raw_value = os.environ.get("MAVERICK_THREAD_TITLE_AI_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return _DEFAULT_TITLE_TIMEOUT_SECONDS
    try:
        parsed = int(raw_value)
    except ValueError:
        return _DEFAULT_TITLE_TIMEOUT_SECONDS
    return min(60, max(3, parsed))


def _json_object(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ThreadTitleGenerationError("title_output_not_object")
    return payload


def _stable_items(items: Iterable[Mapping[str, object]] | None) -> list[dict[str, object]]:
    stable: list[dict[str, object]] = []
    for item in items or []:
        stable.append({str(key): _json_value(item[key]) for key in sorted(item, key=str)})
    return stable


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    return str(value)


def _context_words(
    *,
    input_text: object,
    attachments: Iterable[Mapping[str, object]] | None,
    app_references: Iterable[Mapping[str, object]] | None,
) -> list[str]:
    text_parts = [str(input_text or "")]
    for item in app_references or []:
        text_parts.extend(str(item.get(key) or "") for key in ("label", "title", "entity_type", "app_id"))
    for item in attachments or []:
        text_parts.extend(str(item.get(key) or "") for key in ("name", "filename", "relative_path"))
    words: list[str] = []
    seen: set[str] = set()
    for raw_word in _TITLE_TOKEN.findall(" ".join(text_parts)):
        word = raw_word.strip(".+-")
        key = _word_key(word)
        if not key or key in seen or len(word) <= 1:
            continue
        seen.add(key)
        words.append(_display_word(word))
    return words


def _fallback_suffix(
    *,
    attachments: Iterable[Mapping[str, object]] | None,
    app_references: Iterable[Mapping[str, object]] | None,
) -> list[str]:
    if any(True for _ in attachments or []):
        return ["File", "Allegato"]
    if any(True for _ in app_references or []):
        return ["Riferimento", "Collegato"]
    return ["Primo", "Messaggio"]


def _trim_to_word_limit(title: str, limit: int) -> str:
    pieces = title.split()
    if len(pieces) <= limit:
        return title
    return " ".join(pieces[:limit]).strip(" .,:;!?")


def _bounded_title(value: str) -> str:
    title = " ".join(str(value or "").split()).strip()
    if len(title) <= MAX_THREAD_TITLE_CHARS:
        return title
    bounded = title[:MAX_THREAD_TITLE_CHARS].rsplit(" ", 1)[0].strip()
    return bounded or title[:MAX_THREAD_TITLE_CHARS].strip()


def _display_word(word: str) -> str:
    if any(char.isdigit() for char in word) or word.isupper() or any(char.isupper() for char in word[1:]):
        return word
    return word[:1].upper() + word[1:].lower()


def _word_key(word: str) -> str:
    return str(word or "").strip(".+-").casefold()
