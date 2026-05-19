"""Speech app domain constants and payload helpers."""

from __future__ import annotations

MAX_TEXT_CHARS = 1500
MAX_AUDIO_BYTES = 2_000_000
SUPPORTED_CONTENT_TYPES = ["audio/wav"]
SUPPORTED_SYNTHESIS_ACTIONS = ["capabilities", "health.check", "operations.manifest", "synthesize"]
DEFAULT_VOICE = "en"
DEFAULT_RATE = 175
MIN_RATE = 80
MAX_RATE = 320
