"""FrameAssetFixture fixtures extracted without changing assertions."""

from __future__ import annotations
import hashlib
from pathlib import Path


class FrameAssetFixture:
    @staticmethod
    def _asset_source() -> bytes:
        return ("export const isolatedAsset = 'public-cache';\n" * 80).encode("utf-8")

    @staticmethod
    def _worker_source() -> bytes:
        return ("self.onmessage = () => self.postMessage('ready');\n" * 80).encode("utf-8")

    @staticmethod
    def _audio_source() -> bytes:
        return b"ID3" + bytes(range(256)) * 8

    @staticmethod
    def _wasm_source() -> bytes:
        return b"\x00asm\x01\x00\x00\x00" + b"\x00" * 2048

    @staticmethod
    def _asset_record(frontend_root: Path, relative: str) -> dict[str, object]:
        body = (frontend_root / relative).read_bytes()
        return {
            "path": relative,
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        }
