"""Fail-closed rollout flags and the public PWA kill-switch projection."""

from __future__ import annotations

from collections.abc import Mapping
import os
import re


MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2 = "MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2"
MAVERICK_FEATURE_PWA_DATA_CACHE = "MAVERICK_FEATURE_PWA_DATA_CACHE"
MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE = "MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE"
MAVERICK_FEATURE_PWA_APP_CACHE_PREFIX = "MAVERICK_FEATURE_PWA_APP_CACHE_"

_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
_DEFAULTS = {
    MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2: True,
    MAVERICK_FEATURE_PWA_DATA_CACHE: False,
    MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE: False,
}


def pwa_feature_enabled(
    name: str,
    *,
    environment: Mapping[str, str] | None = None,
    default: bool | None = None,
) -> bool:
    """Resolve one strict boolean flag; malformed configured values disable it."""
    source = os.environ if environment is None else environment
    raw = source.get(name)
    if raw is None or not str(raw).strip():
        return _DEFAULTS.get(name, False) if default is None else default
    normalized = str(raw).strip().lower()
    if normalized in _ENABLED_VALUES:
        return True
    if normalized in _DISABLED_VALUES:
        return False
    return False


def app_data_cache_enabled(app_id: str, *, environment: Mapping[str, str] | None = None) -> bool:
    """Return whether both the global data-cache gate and one app gate are open."""
    normalized_app_id = re.sub(r"[^A-Za-z0-9]", "_", str(app_id or "").strip()).upper()
    if not normalized_app_id or not pwa_feature_enabled(MAVERICK_FEATURE_PWA_DATA_CACHE, environment=environment):
        return False
    return pwa_feature_enabled(
        f"{MAVERICK_FEATURE_PWA_APP_CACHE_PREFIX}{normalized_app_id}",
        environment=environment,
        default=False,
    )


def public_pwa_config(*, environment: Mapping[str, str] | None = None) -> dict[str, object]:
    """Project only redaction-safe browser rollout state for registration/recovery."""
    return {
        "schema": "maverick.pwa-config.v2",
        "service_worker": {
            "enabled": pwa_feature_enabled(MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2, environment=environment),
            "generation": "v2",
        },
        "features": {
            "data_cache": pwa_feature_enabled(MAVERICK_FEATURE_PWA_DATA_CACHE, environment=environment),
            "storage_file_cache": pwa_feature_enabled(
                MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE,
                environment=environment,
            ),
        },
    }
