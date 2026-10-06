"""Per-request local-only transcription without changing workspace preferences."""

from errors import SpeechValidationError


def local_only_requested(body: dict) -> bool:
    value = body.get("local_only", False)
    if not isinstance(value, bool):
        raise SpeechValidationError("local_only must be a boolean.", operation=str(body.get("action") or "transcribe_audio"))
    if value and any(body.get(key) for key in ("session_id", "conversation", "conversation_mode", "dictation", "dictation_mode")):
        raise SpeechValidationError("local_only supports finite one-shot transcription.", operation=str(body.get("action") or "transcribe_audio"))
    return value


def local_transcription_settings(settings: dict, local_only: bool) -> dict:
    if not local_only:
        return settings
    # 'auto' selects only faster-whisper/whisper.cpp. Neither uses remote STT.
    result = {**settings, "transcription_engine": "auto"}
    result.pop("_app_secrets", None)
    result.pop("_provider_config", None)
    return result
