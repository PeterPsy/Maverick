from __future__ import annotations

import unittest

from core.pwa.feature_flags import (
    MAVERICK_FEATURE_PWA_DATA_CACHE,
    MAVERICK_FEATURE_PWA_OFFLINE_OUTBOX,
    MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2,
    MAVERICK_FEATURE_PWA_STORAGE_OFFLINE_FILES,
    app_data_cache_enabled,
    public_pwa_config,
    pwa_feature_enabled,
)


class PwaFeatureFlagTests(unittest.TestCase):
    def test_safe_shell_defaults_on_and_private_persistence_defaults_off(self) -> None:
        environment: dict[str, str] = {}

        self.assertTrue(pwa_feature_enabled(MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2, environment=environment))
        self.assertFalse(pwa_feature_enabled(MAVERICK_FEATURE_PWA_DATA_CACHE, environment=environment))
        self.assertFalse(pwa_feature_enabled(MAVERICK_FEATURE_PWA_STORAGE_OFFLINE_FILES, environment=environment))
        self.assertFalse(pwa_feature_enabled(MAVERICK_FEATURE_PWA_OFFLINE_OUTBOX, environment=environment))

    def test_malformed_values_fail_closed_including_the_shell_kill_switch(self) -> None:
        environment = {MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2: "perhaps"}

        self.assertFalse(pwa_feature_enabled(MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2, environment=environment))

    def test_app_cache_requires_both_global_and_normalized_app_gate(self) -> None:
        self.assertFalse(
            app_data_cache_enabled(
                "website-studio",
                environment={"MAVERICK_FEATURE_PWA_APP_CACHE_WEBSITE_STUDIO": "1"},
            )
        )
        self.assertTrue(
            app_data_cache_enabled(
                "website-studio",
                environment={
                    MAVERICK_FEATURE_PWA_DATA_CACHE: "true",
                    "MAVERICK_FEATURE_PWA_APP_CACHE_WEBSITE_STUDIO": "yes",
                },
            )
        )

    def test_public_config_contains_no_environment_names_or_app_overrides(self) -> None:
        payload = public_pwa_config(
            environment={
                MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2: "0",
                MAVERICK_FEATURE_PWA_DATA_CACHE: "1",
                "MAVERICK_FEATURE_PWA_APP_CACHE_CHAT": "1",
            }
        )

        self.assertEqual(payload["schema"], "maverick.pwa-config.v1")
        self.assertEqual(payload["service_worker"], {"enabled": False, "generation": "v2"})
        self.assertEqual(payload["features"]["data_cache"], True)
        self.assertNotIn("chat", str(payload).lower())
        self.assertNotIn("MAVERICK_", str(payload))


if __name__ == "__main__":
    unittest.main()
