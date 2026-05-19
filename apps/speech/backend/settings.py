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


def list_engines_payload(data_root: Path) -> dict:
    settings = read_settings(data_root)
    return {
        "app_id": "speech",
        "synthesis": synthesis_engine_statuses(),
        "transcription": transcription_engine_statuses(settings),
        "settings": public_settings(settings),
    }


def engine_health_payload(data_root: Path) -> dict:
    payload = list_engines_payload(data_root)
    payload["status"] = "ok" if any(item["available"] for item in payload["synthesis"] + payload["transcription"]) else "degraded"
    return payload


def get_settings_payload(data_root: Path) -> dict:
    return {"settings": public_settings(read_settings(data_root))}


def set_engine_payload(data_root: Path, body: dict) -> dict:
    allowed_fields = {"action", "synthesis_engine", "transcription_engine"}
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
        "faster_whisper_model_configured": faster_whisper_model_configured(),
        "whisper_cpp_model_configured": whisper_cpp_model_configured(),
    }


def normalized_setting(key: str, value: object) -> str:
    text = str(value or "").strip()
    if key == "synthesis_engine" and text not in {"auto", "espeak", "espeak-ng"}:
        raise SpeechValidationError(
            "Unsupported synthesis_engine.",
            operation="set_engine",
            allowed_values={key: ["auto", "espeak", "espeak-ng"]},
        )
    if key == "transcription_engine" and text not in {"auto", "faster-whisper", "whisper.cpp"}:
        raise SpeechValidationError(
            "Unsupported transcription_engine.",
            operation="set_engine",
            allowed_values={key: ["auto", "faster-whisper", "whisper.cpp"]},
        )
    return text
