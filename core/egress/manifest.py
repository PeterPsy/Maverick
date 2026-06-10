"""Shared browser egress policy manifest loader."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
from typing import Any


POLICY_MANIFEST_PATH = Path(__file__).with_name("policy_manifest.json")


@lru_cache(maxsize=1)
def browser_egress_policy_manifest() -> dict[str, Any]:
    """Load the shared Browser egress policy manifest."""

    manifest = json.loads(POLICY_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Browser egress policy manifest must be a JSON object.")
    if manifest.get("schema_version") != "1":
        raise ValueError("Unsupported Browser egress policy manifest schema version.")
    return manifest
