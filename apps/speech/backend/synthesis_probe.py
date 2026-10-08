"""Explicit short synthesis check, returning metadata rather than audio."""

from pathlib import Path

from synthesis import synthesize_payload


def probe_synthesis_payload(*, data_root: Path, generated_storage_root: Path, body: dict) -> dict:
    result = synthesize_payload(
        data_root=data_root,
        generated_storage_root=generated_storage_root,
        body={"text": "Ciao, questa è una prova della voce di Maverick.", "_app_secrets": body.get("_app_secrets", {})},
    )
    return {"probe": {name: result[name] for name in (
        "engine", "voice", "language", "content_type", "size_bytes", "metrics", "retention",
    )}}
