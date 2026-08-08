"""Idempotent migrate hook for SDK-generated data apps."""

from __future__ import annotations

from core.app_sdk.runtime import emit_json


emit_json({"ok": True})
