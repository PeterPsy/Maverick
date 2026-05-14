"""Deterministic runtime thread title generation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
import unicodedata

from core.runtime.thread_title_vocabulary import (
    ACTION_REPLACEMENTS as _ACTION_REPLACEMENTS,
    CONVERSION_KEYS as _CONVERSION_KEYS,
    DISPLAY_REPLACEMENTS as _DISPLAY_REPLACEMENTS,
    FIX_KEYS as _FIX_KEYS,
    FORMAT_KEYS as _FORMAT_KEYS,
    IMPLEMENTATION_ACTIONS as _IMPLEMENTATION_ACTIONS,
    IMPROVEMENT_KEYS as _IMPROVEMENT_KEYS,
    INTENT_KEYS as _INTENT_KEYS,
    LOW_SIGNAL_KEYS as _LOW_SIGNAL_KEYS,
    PRODUCT_KEYS as _PRODUCT_KEYS,
    STOPWORDS as _STOPWORDS,
    STRONG_TOPIC_KEYS as _STRONG_TOPIC_KEYS,
)


DEFAULT_THREAD_TITLE = "New chat"
MAX_THREAD_TITLE_CHARS = 80
MAX_THREAD_TITLE_WORDS = 5

_ENTITY_REFERENCE_MARKER = re.compile(r"\[ref:[^\]\s]+/[^\]\s]+/[^\]\s]+\]")
_FENCED_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_TOKEN = re.compile(r"[^\W_]+(?:[.+][^\W_]+)*", re.UNICODE)
_FILE_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,8}$")


@dataclass(frozen=True)
class _ScoredToken:
    key: str
    display: str
    score: int
    index: int


def derive_thread_title(
    input_text: object,
    *,
    attachments: Iterable[Mapping[str, object]] | None = None,
    app_references: Iterable[Mapping[str, object]] | None = None,
) -> str:
    """Return a compact contextual title for a first user message."""
    message_text = _message_text(input_text)
    reference_text = _labels_from_items(
        app_references,
        ("label", "title", "entity_id", "app_id"),
        strip_extension=False,
    )
    attachment_text = _labels_from_items(attachments, ("name", "filename", "relative_path"), strip_extension=True)
    title = _title_from_parts(message_text, reference_text=reference_text, attachment_text=attachment_text)
    return _bounded_title(title) or DEFAULT_THREAD_TITLE


def normalized_title_input(value: object) -> str:
    """Return the canonical message text used for title input comparisons."""
    return _message_text(value)


def _title_from_parts(message_text: str, *, reference_text: str = "", attachment_text: str = "") -> str:
    combined_text = " ".join(part for part in (message_text, reference_text, attachment_text) if part)
    if not combined_text:
        return DEFAULT_THREAD_TITLE
    action = _select_action(message_text)
    candidates = _candidate_tokens(message_text, reference_text=reference_text, attachment_text=attachment_text)
    words = _assemble_title_words(action, candidates)
    if len(words) >= 2:
        return " ".join(words)
    fallback = _short_phrase_title(message_text or reference_text or attachment_text)
    if fallback:
        return fallback
    return " ".join(words) if words else DEFAULT_THREAD_TITLE


def _select_action(message_text: str) -> str:
    keys = _token_keys(message_text)
    if not keys:
        return ""
    key_set = set(keys)
    if key_set & _CONVERSION_KEYS and key_set & _FORMAT_KEYS:
        return "Conversione"
    if key_set & _IMPROVEMENT_KEYS:
        return "Migliorare"
    for key in keys:
        if key in _FIX_KEYS:
            return "Fix"
    for key in keys:
        if key in {"analisi", "analizza", "analizzare", "analyze", "esamina", "esaminare"}:
            return "Analisi"
    for key in keys:
        if key in {"problema"}:
            return "Problema"
    for key in keys:
        if key in {"review"}:
            return "Review"
    for key in keys:
        if key in {"controlla", "controllare", "verifica", "verificare"}:
            return "Verifica"
    for index, key in enumerate(keys):
        if key in _IMPLEMENTATION_ACTIONS and index <= 6:
            return _IMPLEMENTATION_ACTIONS[key]
    for key in keys:
        if key in {"ricerca", "trova", "trovare"}:
            return "Ricerca"
    return ""


def _candidate_tokens(message_text: str, *, reference_text: str = "", attachment_text: str = "") -> list[_ScoredToken]:
    candidates: dict[str, _ScoredToken] = {}
    focus_keys = _focus_keys(message_text)
    index_offset = 0
    index_offset = _add_tokens(candidates, message_text, base_score=10, focus_keys=focus_keys, index_offset=index_offset)
    index_offset = _add_tokens(candidates, reference_text, base_score=60, focus_keys=set(), index_offset=index_offset)
    _add_tokens(candidates, attachment_text, base_score=55, focus_keys=set(), index_offset=index_offset)
    return sorted(candidates.values(), key=lambda item: (-item.score, item.index, item.display.casefold()))


def _add_tokens(
    candidates: dict[str, _ScoredToken],
    text: str,
    *,
    base_score: int,
    focus_keys: set[str],
    index_offset: int,
) -> int:
    token_count = 0
    previous_key = ""
    for raw_token in _TOKEN.findall(_message_text(text)):
        key = _normalized_key(raw_token)
        token_count += 1
        if (raw_token.isdigit() and base_score < 55) or _skip_topic_key(key):
            previous_key = key
            continue
        if key == "report" and raw_token.islower() and base_score < 55 and previous_key in {"un", "una"}:
            previous_key = key
            continue
        display = _display_token(raw_token)
        if not display:
            previous_key = key
            continue
        score = base_score + _topic_score(key, raw_token)
        if key in focus_keys:
            score += 20
        if previous_key in {"app"} and key == "store":
            score += 20
        index = index_offset + token_count
        existing = candidates.get(key)
        if existing is None or (score, -index) > (existing.score, -existing.index):
            candidates[key] = _ScoredToken(key=key, display=display, score=score, index=index)
        previous_key = key
    return index_offset + token_count


def _focus_keys(text: str) -> set[str]:
    keys = _token_keys(text)
    focused: set[str] = set()
    for index, key in enumerate(keys):
        if key not in _INTENT_KEYS:
            continue
        for nearby in keys[index + 1 : index + 14]:
            if not _skip_topic_key(nearby):
                focused.add(nearby)
    return focused


def _topic_score(key: str, raw_token: str) -> int:
    score = 0
    if key in _PRODUCT_KEYS:
        score += 25
    if key in _STRONG_TOPIC_KEYS:
        score += 25
    if key in _FORMAT_KEYS:
        score += 30
    if any(char.isdigit() for char in raw_token) or raw_token.isupper():
        score += 12
    if len(key) >= 9:
        score += 4
    return score


def _assemble_title_words(action: str, candidates: list[_ScoredToken]) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    if action:
        _append_title_words(words, seen, action)
    selected: list[_ScoredToken] = []
    for candidate in candidates:
        if len(words) + sum(len(item.display.split()) for item in selected) >= MAX_THREAD_TITLE_WORDS:
            break
        if action and _normalized_key(candidate.display) == _normalized_key(action):
            continue
        selected.append(candidate)
    if action or any(item.key in {"caricamento", "cartella", "cartelle", "skeleton"} for item in selected):
        selected.sort(key=lambda item: (item.key in _PRODUCT_KEYS, item.index))
    else:
        selected.sort(key=lambda item: item.index)
    for candidate in selected:
        _append_title_words(words, seen, candidate.display)
    return words[:MAX_THREAD_TITLE_WORDS]


def _append_title_words(words: list[str], seen: set[str], display: str) -> None:
    for word in display.split():
        if len(words) >= MAX_THREAD_TITLE_WORDS:
            return
        key = _normalized_key(word)
        if not key or key in seen:
            continue
        words.append(word)
        seen.add(key)


def _short_phrase_title(text: str) -> str:
    raw_tokens = _TOKEN.findall(_message_text(text))
    keys = [_normalized_key(token) for token in raw_tokens]
    if not keys or all(key in {"ciao", "ok"} for key in keys):
        return ""
    meaningful = [key for key in keys if key not in _LOW_SIGNAL_KEYS]
    if len(raw_tokens) <= MAX_THREAD_TITLE_WORDS and meaningful:
        return " ".join(_display_token(token) for token in raw_tokens if _display_token(token))
    return ""


def _token_keys(text: str) -> list[str]:
    return [_normalized_key(token) for token in _TOKEN.findall(_message_text(text)) if _normalized_key(token)]


def _skip_topic_key(key: str) -> bool:
    return not key or key in _STOPWORDS or key in _LOW_SIGNAL_KEYS or key in _ACTION_REPLACEMENTS or key in _IMPLEMENTATION_ACTIONS


def _message_text(value: object) -> str:
    text = str(value or "")
    text = _FENCED_CODE_BLOCK.sub(" ", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _ENTITY_REFERENCE_MARKER.sub(" ", text)
    text = re.sub(r"`([^`]*)`", r" \1 ", text)
    text = re.sub(r"[@#$*_~>|{}()\[\],;:!?\"']", " ", text)
    text = text.replace("/", " ").replace("\\", " ").replace("-", " ").replace("_", " ")
    return " ".join(text.split())


def _labels_from_items(
    items: Iterable[Mapping[str, object]] | None,
    keys: tuple[str, ...],
    *,
    strip_extension: bool,
) -> str:
    labels: list[str] = []
    for item in items or []:
        label = ""
        for key in keys:
            value = str(item.get(key) or "").strip()
            if value:
                label = value
                break
        if not label:
            continue
        label = label.replace("\\", "/").rsplit("/", 1)[-1]
        if strip_extension:
            label = _FILE_EXTENSION.sub("", label)
        labels.append(label)
    return " ".join(labels)


def _display_token(token: str) -> str:
    value = token.strip(".+-")
    if not value:
        return ""
    key = _normalized_key(value)
    replacement = _DISPLAY_REPLACEMENTS.get(key)
    if replacement is not None:
        return replacement
    if any(char.isdigit() for char in value) or value.isupper() or any(char.isupper() for char in value[1:]):
        return value
    return value[:1].upper() + value[1:].lower()


def _normalized_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return ascii_text.strip(".+-").casefold()


def _bounded_title(value: str) -> str:
    title = " ".join(str(value or "").split()).strip()
    if len(title) <= MAX_THREAD_TITLE_CHARS:
        return title
    bounded = title[:MAX_THREAD_TITLE_CHARS].rsplit(" ", 1)[0].strip()
    return bounded or title[:MAX_THREAD_TITLE_CHARS].strip()
