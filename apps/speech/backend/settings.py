"""Speech workspace settings and engine status payloads."""

from __future__ import annotations

import re
from pathlib import Path

from engines import (
    faster_whisper_initial_prompt,
    faster_whisper_model_configured,
    synthesis_engine_statuses,
    transcription_engine_statuses,
    whisper_cpp_model_configured,
)
from errors import SpeechValidationError
from store import read_settings, write_settings

SYNTHESIS_AUTO_ENGINES = ("piper", "espeak-ng", "espeak")
TRANSCRIPTION_AUTO_ENGINES = ("faster-whisper", "whisper.cpp")


def list_engines_payload(data_root: Path, *, include_voices: bool = True, app_secrets: dict | None = None) -> dict:
    settings = settings_with_app_secrets(data_root, app_secrets)
    synthesis = synthesis_engine_statuses(settings)
    if not include_voices:
        synthesis = compact_voice_statuses(synthesis)
    return {
        "app_id": "speech",
        "synthesis": synthesis,
        "transcription": transcription_engine_statuses(settings),
        "settings": public_settings(settings),
    }


def engine_health_payload(data_root: Path, *, include_voices: bool = True, app_secrets: dict | None = None) -> dict:
    payload = list_engines_payload(data_root, include_voices=include_voices, app_secrets=app_secrets)
    settings = settings_with_app_secrets(data_root, app_secrets)
    synthesis_selection = engine_selection_summary(
        payload["synthesis"],
        requested_engine=str(settings.get("synthesis_engine") or "auto"),
        auto_candidates=SYNTHESIS_AUTO_ENGINES,
    )
    transcription_selection = engine_selection_summary(
        payload["transcription"],
        requested_engine=str(settings.get("transcription_engine") or "auto"),
        auto_candidates=TRANSCRIPTION_AUTO_ENGINES,
    )
    synthesis_available = bool(synthesis_selection["available"])
    transcription_available = bool(transcription_selection["available"])
    payload["status"] = combined_interface_status(synthesis_available=synthesis_available, transcription_available=transcription_available)
    payload["selected"] = {
        "synthesis": synthesis_selection,
        "transcription": transcription_selection,
    }
    payload["interfaces"] = {
        "speech.synthesis": interface_health_summary(synthesis_selection),
        "speech.transcription": interface_health_summary(transcription_selection),
    }
    return payload


def get_settings_payload(data_root: Path) -> dict:
    return {"settings": public_settings(read_settings(data_root))}


def settings_with_app_secrets(data_root: Path, app_secrets: dict | None = None) -> dict:
    settings = read_settings(data_root)
    if isinstance(app_secrets, dict):
        return {**settings, "_app_secrets": dict(app_secrets)}
    return settings


def compact_voice_statuses(statuses: list[dict]) -> list[dict]:
    compacted: list[dict] = []
    for item in statuses:
        payload = dict(item)
        if "voices" in payload:
            voices = payload.pop("voices")
            payload["voice_count"] = len(voices) if isinstance(voices, list) else 0
        compacted.append(payload)
    return compacted


def engine_selection_summary(statuses: list[dict], *, requested_engine: str, auto_candidates: tuple[str, ...]) -> dict:
    requested = requested_engine.strip() or "auto"
    by_engine = {str(item.get("engine") or ""): item for item in statuses if isinstance(item, dict)}
    selected_status = selected_engine_status(by_engine, requested_engine=requested, auto_candidates=auto_candidates)
    selected_engine = str((selected_status or {}).get("engine") or "")
    available_engines = [str(item.get("engine") or "") for item in statuses if isinstance(item, dict) and item.get("available")]
    fallback_engines = [engine for engine in available_engines if engine and engine != selected_engine]
    return {
        "requested_engine": requested,
        "effective_engine": selected_engine if selected_status and selected_status.get("available") else "",
        "available": bool(selected_status and selected_status.get("available")),
        "selected_engine_known": bool(selected_status),
        "fallback_available": bool(fallback_engines),
        "fallback_engines": fallback_engines,
        "available_engine_count": len([engine for engine in available_engines if engine]),
    }


def selected_engine_status(by_engine: dict[str, dict], *, requested_engine: str, auto_candidates: tuple[str, ...]) -> dict | None:
    if requested_engine == "auto":
        for engine in auto_candidates:
            status = by_engine.get(engine)
            if status and status.get("available"):
                return status
        return None
    return by_engine.get(requested_engine)


def interface_health_summary(selection: dict) -> dict:
    return {
        "available": bool(selection.get("available")),
        "selected_available": bool(selection.get("available")),
        "selected_engine": selection.get("requested_engine", ""),
        "effective_engine": selection.get("effective_engine", ""),
        "fallback_available": bool(selection.get("fallback_available")),
        "fallback_engines": list(selection.get("fallback_engines") or []),
    }


def set_engine_payload(data_root: Path, body: dict) -> dict:
    allowed_fields = {"action", "synthesis_engine", "synthesis_language", "transcription_engine", "transcription_profile", "_app_secrets"}
    unexpected_fields = sorted(set(body) - allowed_fields)
    if unexpected_fields:
        raise SpeechValidationError(
            f"Unsupported setting field(s): {', '.join(unexpected_fields)}.",
            operation="set_engine",
            allowed_values={"fields": sorted(allowed_fields - {"action"})},
        )
    updates: dict[str, str] = {}
    for key in (
        "synthesis_engine",
        "synthesis_language",
        "transcription_engine",
        "transcription_profile",
    ):
        if key in body:
            updates[key] = normalized_setting(key, body.get(key))
    settings = write_settings(data_root, updates)
    app_secrets = body.get("_app_secrets") if isinstance(body.get("_app_secrets"), dict) else None
    return {"settings": public_settings(settings), "engines": list_engines_payload(data_root, app_secrets=app_secrets)}


def public_settings(settings: dict) -> dict:
    return {
        "schema_version": settings.get("schema_version", "1"),
        "synthesis_engine": settings.get("synthesis_engine", "auto"),
        "synthesis_language": settings.get("synthesis_language", "auto"),
        "transcription_engine": settings.get("transcription_engine", "auto"),
        "transcription_profile": settings.get("transcription_profile", "balanced"),
        "faster_whisper_model_configured": faster_whisper_model_configured(settings),
        "transcription_prompt_configured": bool(faster_whisper_initial_prompt()),
        "whisper_cpp_model_configured": whisper_cpp_model_configured(),
    }


def normalized_setting(key: str, value: object) -> str:
    text = str(value or "").strip()
    if key == "synthesis_engine" and text not in {"auto", "piper", "espeak", "espeak-ng", "kokoro-openrouter", "kokoro-deepinfra"}:
        raise SpeechValidationError(
            "Unsupported synthesis_engine.",
            operation="set_engine",
            allowed_values={key: ["auto", "piper", "espeak", "espeak-ng", "kokoro-openrouter", "kokoro-deepinfra"]},
        )
    if key == "synthesis_language":
        normalized = text.lower().replace("_", "-")
        if normalized != "auto" and not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", normalized):
            raise SpeechValidationError(
                "Unsupported synthesis_language.",
                operation="set_engine",
                allowed_values={key: ["auto", "BCP-47 language tag such as it-IT or en-US"]},
            )
        return normalized
    if key == "transcription_engine" and text not in {"auto", "faster-whisper", "whisper.cpp", "deepgram"}:
        raise SpeechValidationError(
            "Unsupported transcription_engine.",
            operation="set_engine",
            allowed_values={key: ["auto", "faster-whisper", "whisper.cpp", "deepgram"]},
        )
    if key == "transcription_profile" and text not in {"fast", "balanced", "accurate"}:
        raise SpeechValidationError(
            "Unsupported transcription_profile.",
            operation="set_engine",
            allowed_values={key: ["fast", "balanced", "accurate"]},
        )
    return text


def combined_interface_status(*, synthesis_available: bool, transcription_available: bool) -> str:
    if synthesis_available and transcription_available:
        return "ok"
    if synthesis_available or transcription_available:
        return "partial"
    return "degraded"
