"""Platform-owned policy primitives for Maverick web-app caching."""

from core.pwa.feature_flags import (
    MAVERICK_FEATURE_PWA_DATA_CACHE,
    MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2,
    MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE,
    app_data_cache_enabled,
    pwa_feature_enabled,
    public_pwa_config,
)

__all__ = [
    "MAVERICK_FEATURE_PWA_DATA_CACHE",
    "MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2",
    "MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE",
    "app_data_cache_enabled",
    "public_pwa_config",
    "pwa_feature_enabled",
]
