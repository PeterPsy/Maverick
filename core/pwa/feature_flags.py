"""Fail-closed rollout flags and the public PWA kill-switch projection."""

from __future__ import annotations

from collections.abc import Mapping
import os
import re

from core.pwa.rollout import pwa_rollout_allows


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


def app_data_cache_enabled(
    app_id: str,
    *,
    environment: Mapping[str, str] | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> bool:
    """Return whether both the global data-cache gate and one app gate are open."""
    normalized_app_id = re.sub(r"[^A-Za-z0-9]", "_", str(app_id or "").strip()).upper()
    if not normalized_app_id or not _feature_enabled_for_cohort(
        MAVERICK_FEATURE_PWA_DATA_CACHE,
        environment=environment,
        user_id=user_id,
        workspace_id=workspace_id,
    ):
        return False
    app_flag = f"{MAVERICK_FEATURE_PWA_APP_CACHE_PREFIX}{normalized_app_id}"
    return _feature_enabled_for_cohort(
        app_flag,
        environment=environment,
        default=False,
        user_id=user_id,
        workspace_id=workspace_id,
    )


def public_pwa_config(
    *,
    environment: Mapping[str, str] | None = None,
    user_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, object]:
    """Project only redaction-safe browser rollout state for registration/recovery."""
    return {
        "schema": "maverick.pwa-config.v2",
        "service_worker": {
            "enabled": _feature_enabled_for_cohort(
                MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2,
                environment=environment,
                user_id=user_id,
                workspace_id=workspace_id,
            ),
            "generation": "v2",
        },
        "features": {
            "data_cache": _feature_enabled_for_cohort(
                MAVERICK_FEATURE_PWA_DATA_CACHE,
                environment=environment,
                user_id=user_id,
                workspace_id=workspace_id,
            ),
            "storage_file_cache": _feature_enabled_for_cohort(
                MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE,
                environment=environment,
                user_id=user_id,
                workspace_id=workspace_id,
            ),
        },
    }


def _feature_enabled_for_cohort(
    name: str,
    *,
    environment: Mapping[str, str] | None,
    user_id: str | None,
    workspace_id: str | None,
    default: bool | None = None,
) -> bool:
    return pwa_feature_enabled(name, environment=environment, default=default) and pwa_rollout_allows(
        name,
        environment=environment,
        user_id=user_id,
        workspace_id=workspace_id,
    )
