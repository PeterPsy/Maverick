"""Speech app domain constants."""

from __future__ import annotations

MAX_TEXT_CHARS = 1500
MAX_AUDIO_BYTES = 2_000_000
MAX_TRANSCRIPTION_AUDIO_BYTES = 20_000_000
MIN_TRANSCRIPTION_AUDIO_BYTES = 128
MAX_TRANSCRIPTION_SECONDS = 180
SUPPORTED_CONTENT_TYPES = ["audio/wav"]
SUPPORTED_TRANSCRIPTION_CONTENT_TYPES = [
    "audio/flac",
    "audio/m4a",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "video/mp4",
    "video/webm",
]
SUPPORTED_ACTIONS = [
    "capabilities",
    "engine_health",
    "get_settings",
    "health.check",
    "list_engines",
    "operations.manifest",
    "set_engine",
    "synthesize",
    "transcribe_audio",
    "transcribe_file",
]
DEFAULT_VOICE = "en"
DEFAULT_RATE = 175
MIN_RATE = 80
MAX_RATE = 320
DEFAULT_TRANSCRIPTION_ENGINE = "auto"
DEFAULT_FASTER_WHISPER_MODEL = "base"
DEFAULT_FASTER_WHISPER_DEVICE = "auto"
DEFAULT_FASTER_WHISPER_COMPUTE_TYPE = "default"
