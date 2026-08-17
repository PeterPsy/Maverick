"""Shared bounded JSON encoding and SSE decoding for agentic transports."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import asyncio
import json


ProtocolErrorFactory = Callable[[str], Exception]


def encode_bounded_json(
    payload: dict[str, object],
    *,
    max_bytes: int,
    error: ProtocolErrorFactory,
) -> bytes:
    """Encode a finite JSON object or fail with a provider-safe reason."""
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as cause:
        raise error("provider_request_invalid") from cause
    if len(encoded) > max_bytes:
        raise error("provider_request_invalid")
    return encoded


async def read_bounded_json_sse(
    response,
    *,
    max_event_bytes: int,
    max_stream_bytes: int,
    error: ProtocolErrorFactory,
) -> AsyncIterator[dict[str, object]]:
    """Decode a complete, bounded SSE stream containing JSON data events."""
    data_lines: list[bytes] = []
    event_bytes = 0
    total_bytes = 0
    saw_done = False
    while True:
        line = await asyncio.to_thread(response.readline, max_event_bytes + 1)
        if not line:
            break
        total_bytes += len(line)
        if len(line) > max_event_bytes or total_bytes > max_stream_bytes:
            raise error("provider_response_invalid")
        stripped = line.rstrip(b"\r\n")
        if stripped.startswith(b"data:"):
            value = stripped[5:].lstrip()
            data_lines.append(value)
            event_bytes += len(value)
            if event_bytes > max_event_bytes:
                raise error("provider_response_invalid")
            continue
        if stripped or not data_lines:
            continue
        data = b"\n".join(data_lines)
        data_lines = []
        event_bytes = 0
        if data == b"[DONE]":
            saw_done = True
            break
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as cause:
            raise error("provider_response_invalid") from cause
        if not isinstance(payload, dict):
            raise error("provider_response_invalid")
        yield payload
    if data_lines or not saw_done:
        raise error("provider_response_invalid")
