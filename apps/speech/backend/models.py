"""Speech app domain constants."""

from __future__ import annotations

MAX_TEXT_CHARS = 1500
MAX_AUDIO_BYTES = 2_000_000
TTS_CACHE_MAX_BYTES = 20_000_000
TTS_CACHE_MAX_FILES = 64
TTS_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
TTS_CACHE_HASH_MAX_BYTES = 5_000_000
MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES = 700_000
MAX_TRANSCRIPTION_FILE_AUDIO_BYTES = 20_000_000
MAX_TRANSCRIPTION_AUDIO_BYTES = MAX_INLINE_TRANSCRIPTION_AUDIO_BYTES
MIN_TRANSCRIPTION_AUDIO_BYTES = 128
MAX_INLINE_TRANSCRIPTION_SECONDS = 120
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
    "prewarm_worker",
    "set_engine",
    "synthesize",
    "transcribe_audio",
    "transcribe_file",
    "worker_status",
]
DEFAULT_SYNTHESIS_ENGINE = "auto"
DEFAULT_VOICE = "en"
DEFAULT_RATE = 175
MIN_RATE = 80
MAX_RATE = 320
DEFAULT_TRANSCRIPTION_ENGINE = "auto"
DEFAULT_TRANSCRIPTION_PROFILE = "balanced"
DEFAULT_INLINE_TRANSCRIPTION_PROFILE = "fast"
TRANSCRIPTION_PROFILE_MODELS = {
    "fast": "base",
    "balanced": "small",
    "accurate": "medium",
}
TRANSCRIPTION_PROFILE_BEAM_SIZES = {
    "fast": 1,
    "balanced": 5,
    "accurate": 5,
}
TRANSCRIPTION_PROFILE_DEVICE_DEFAULTS = {
    "fast": "cpu",
    "balanced": "auto",
    "accurate": "auto",
}
TRANSCRIPTION_PROFILE_COMPUTE_TYPE_DEFAULTS = {
    "fast": "int8",
    "balanced": "default",
    "accurate": "default",
}
DEFAULT_FASTER_WHISPER_MODEL = TRANSCRIPTION_PROFILE_MODELS[DEFAULT_TRANSCRIPTION_PROFILE]
DEFAULT_FASTER_WHISPER_DEVICE = "auto"
DEFAULT_FASTER_WHISPER_COMPUTE_TYPE = "default"
TTS_CACHE_CLEANUP_INTERVAL_SECONDS = 5 * 60
