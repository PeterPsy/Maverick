"""Bounded decoding of Gemini Interactions SSE audio events."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Iterator

from errors import SpeechProviderUnavailableError
from models import MAX_AUDIO_BYTES


MAX_EVENT_BYTES = (MAX_AUDIO_BYTES * 4 // 3) + 8192
MAX_STREAM_BYTES = MAX_EVENT_BYTES + 1_048_576


def iter_sse_events(response, *, cancelled) -> Iterator[dict]:
    buffer = b""
    data: list[bytes] = []
    event_size = 0
    total_size = 0
    saw_done = False
    while not cancelled():
        chunk = response.read1(16 * 1024)
        if not chunk:
            if buffer or data or not saw_done:
                raise SpeechProviderUnavailableError("Gemini returned an incomplete speech event.")
            return
        total_size += len(chunk)
        if total_size > MAX_STREAM_BYTES:
            raise SpeechProviderUnavailableError("Gemini speech stream exceeds the response size limit.")
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.rstrip(b"\r")
            event_size += len(line)
            if event_size > MAX_EVENT_BYTES:
                raise SpeechProviderUnavailableError("Gemini speech event exceeds the response size limit.")
            if not line:
                if data:
                    encoded = b"\n".join(data)
                    if encoded == b"[DONE]" and not saw_done:
                        saw_done = True
                        data, event_size = [], 0
                        continue
                    if saw_done:
                        raise SpeechProviderUnavailableError("Gemini returned an invalid speech event.")
                    try:
                        event = json.loads(encoded)
                    except (ValueError, UnicodeError) as error:
                        raise SpeechProviderUnavailableError("Gemini returned an invalid speech event.") from error
                    if not isinstance(event, dict):
                        raise SpeechProviderUnavailableError("Gemini returned an invalid speech event.")
                    yield event
                data, event_size = [], 0
            elif line.startswith(b"data:"):
                data.append(line[5:].lstrip())
        if len(buffer) + event_size > MAX_EVENT_BYTES:
            raise SpeechProviderUnavailableError("Gemini speech event exceeds the response size limit.")


def decode_audio_delta(delta: dict) -> bytes:
    mime_type = str(delta.get("mime_type") or "audio/l16").split(";", 1)[0].lower()
    if mime_type != "audio/l16":
        raise SpeechProviderUnavailableError("Gemini returned an unsupported streaming audio format.")
    if delta.get("sample_rate", 24000) != 24000 or delta.get("channels", 1) != 1:
        raise SpeechProviderUnavailableError("Gemini returned an unsupported PCM audio description.")
    data = delta.get("data")
    if not isinstance(data, str):
        raise SpeechProviderUnavailableError("Gemini returned an invalid speech audio chunk.")
    try:
        return base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as error:
        raise SpeechProviderUnavailableError("Gemini returned an invalid speech audio chunk.") from error
