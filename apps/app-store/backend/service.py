"""App-store app service layer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import urlopen

from store import load_state, remember_install


DEFAULT_CATALOG_URL = "https://maverick-app-store.versy.ai"


class AppStoreValidationError(ValueError):
    """Raised when an app-store request payload is invalid."""


def catalog_url() -> str:
    return os.environ.get("MAVERICK_APP_STORE_URL", DEFAULT_CATALOG_URL).strip().rstrip("/")


def fetch_catalog() -> dict[str, Any]:
    url = urljoin(catalog_url().rstrip("/") + "/", "api/apps")
    with urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise AppStoreValidationError("Catalog response must be a JSON object.")
    return payload


def handle_action(data_root: Path, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    action = str(body.get("action") or "catalog")
    if action == "state":
        return 200, {"state": load_state(data_root), "catalog_url": catalog_url()}
    if action == "catalog":
        return 200, fetch_catalog()
    if action == "remember_install":
        app_id = str(body.get("app_id") or "").strip()
        version = str(body.get("version") or "").strip()
        raw_workspace_ids = body.get("workspace_ids")
        workspace_ids = [str(item).strip() for item in raw_workspace_ids] if isinstance(raw_workspace_ids, list) else []
        if not app_id or not version or not workspace_ids:
            raise AppStoreValidationError("app_id, version, and workspace_ids are required.")
        return 200, {"state": remember_install(data_root, app_id=app_id, version=version, workspace_ids=workspace_ids)}
    raise AppStoreValidationError(f"Unknown action `{action}`.")
