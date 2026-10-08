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


def file_timing_request(body: dict) -> tuple[bool, int | None]:
    requested = body.get("word_timestamps", False)
    if not isinstance(requested, bool):
        raise SpeechValidationError("word_timestamps must be a boolean.", operation="transcribe_file")
    limit = body.get("subtitle_max_words")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20):
        raise SpeechValidationError("subtitle_max_words must be an integer in 1...20.", operation="transcribe_file")
    return requested or limit is not None, limit
