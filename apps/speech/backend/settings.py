"""Speech workspace settings and engine status payloads."""

from __future__ import annotations

from pathlib import Path

from engines import (
    faster_whisper_model_configured,
    synthesis_engine_statuses,
    transcription_engine_statuses,
    whisper_cpp_model_configured,
)
from errors import SpeechValidationError
from store import read_settings, write_settings


def list_engines_payload(data_root: Path, *, include_voices: bool = True) -> dict:
    settings = read_settings(data_root)
    synthesis = synthesis_engine_statuses()
    if not include_voices:
        synthesis = compact_voice_statuses(synthesis)
    return {
        "app_id": "speech",
        "synthesis": synthesis,
        "transcription": transcription_engine_statuses(settings),
        "settings": public_settings(settings),
    }


def engine_health_payload(data_root: Path, *, include_voices: bool = True) -> dict:
    payload = list_engines_payload(data_root, include_voices=include_voices)
    synthesis_available = any(item["available"] for item in payload["synthesis"])
    transcription_available = any(item["available"] for item in payload["transcription"])
    payload["status"] = combined_interface_status(synthesis_available=synthesis_available, transcription_available=transcription_available)
    payload["interfaces"] = {
        "speech.synthesis": {"available": synthesis_available},
        "speech.transcription": {"available": transcription_available},
    }
    return payload


def get_settings_payload(data_root: Path) -> dict:
    return {"settings": public_settings(read_settings(data_root))}


def compact_voice_statuses(statuses: list[dict]) -> list[dict]:
    compacted: list[dict] = []
    for item in statuses:
        payload = dict(item)
        if "voices" in payload:
            voices = payload.pop("voices")
            payload["voice_count"] = len(voices) if isinstance(voices, list) else 0
        compacted.append(payload)
    return compacted


def set_engine_payload(data_root: Path, body: dict) -> dict:
    allowed_fields = {"action", "synthesis_engine", "transcription_engine", "transcription_profile"}
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
        "transcription_engine",
        "transcription_profile",
    ):
        if key in body:
            updates[key] = normalized_setting(key, body.get(key))
    settings = write_settings(data_root, updates)
    return {"settings": public_settings(settings), "engines": list_engines_payload(data_root)}


def public_settings(settings: dict) -> dict:
    return {
        "schema_version": settings.get("schema_version", "1"),
        "synthesis_engine": settings.get("synthesis_engine", "auto"),
        "transcription_engine": settings.get("transcription_engine", "auto"),
        "transcription_profile": settings.get("transcription_profile", "balanced"),
        "faster_whisper_model_configured": faster_whisper_model_configured(settings),
        "whisper_cpp_model_configured": whisper_cpp_model_configured(),
    }


def normalized_setting(key: str, value: object) -> str:
    text = str(value or "").strip()
    if key == "synthesis_engine" and text not in {"auto", "piper", "espeak", "espeak-ng"}:
        raise SpeechValidationError(
            "Unsupported synthesis_engine.",
            operation="set_engine",
            allowed_values={key: ["auto", "piper", "espeak", "espeak-ng"]},
        )
    if key == "transcription_engine" and text not in {"auto", "faster-whisper", "whisper.cpp"}:
        raise SpeechValidationError(
            "Unsupported transcription_engine.",
            operation="set_engine",
            allowed_values={key: ["auto", "faster-whisper", "whisper.cpp"]},
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
