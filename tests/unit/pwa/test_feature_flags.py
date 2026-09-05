from __future__ import annotations

import unittest

from core.pwa.feature_flags import (
    MAVERICK_FEATURE_PWA_DATA_CACHE,
    MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2,
    MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE,
    app_data_cache_enabled,
    public_pwa_config,
    pwa_feature_enabled,
)
from core.pwa.rollout import (
    ROLLOUT_USER_PERCENT_SUFFIX,
    ROLLOUT_WORKSPACE_PERCENT_SUFFIX,
    pwa_rollout_allows,
)


class PwaFeatureFlagTests(unittest.TestCase):
    def test_safe_shell_defaults_on_and_private_persistence_defaults_off(self) -> None:
        environment: dict[str, str] = {}

        self.assertTrue(pwa_feature_enabled(MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2, environment=environment))
        self.assertFalse(pwa_feature_enabled(MAVERICK_FEATURE_PWA_DATA_CACHE, environment=environment))
        self.assertFalse(pwa_feature_enabled(MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE, environment=environment))

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
                MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE: "true",
                "MAVERICK_FEATURE_PWA_APP_CACHE_CHAT": "1",
            }
        )

        self.assertEqual(payload["schema"], "maverick.pwa-config.v2")
        self.assertEqual(payload["service_worker"], {"enabled": False, "generation": "v2"})
        self.assertEqual(payload["features"], {"data_cache": True, "storage_file_cache": True})
        self.assertNotIn("outbox", str(payload).lower())
        self.assertNotIn("chat", str(payload).lower())
        self.assertNotIn("MAVERICK_", str(payload))

    def test_rollout_is_deterministic_monotonic_and_requires_partial_dimension_identity(self) -> None:
        flag = MAVERICK_FEATURE_PWA_DATA_CACHE
        half = {f"{flag}{ROLLOUT_WORKSPACE_PERCENT_SUFFIX}": "50"}
        selected = [
            workspace_id
            for workspace_id in (f"workspace-{index}" for index in range(100))
            if pwa_rollout_allows(flag, environment=half, workspace_id=workspace_id)
        ]

        self.assertTrue(selected)
        self.assertLess(len(selected), 100)
        self.assertEqual(
            selected,
            [
                workspace_id
                for workspace_id in (f"workspace-{index}" for index in range(100))
                if pwa_rollout_allows(flag, environment=half, workspace_id=workspace_id)
            ],
        )
        self.assertFalse(pwa_rollout_allows(flag, environment=half, workspace_id=None))
        self.assertTrue(
            all(
                pwa_rollout_allows(
                    flag,
                    environment={f"{flag}{ROLLOUT_WORKSPACE_PERCENT_SUFFIX}": "75"},
                    workspace_id=workspace_id,
                )
                for workspace_id in selected
            )
        )

    def test_rollout_percentages_fail_closed_and_intersect_workspace_and_user(self) -> None:
        flag = MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE
        self.assertFalse(
            pwa_rollout_allows(
                flag,
                environment={f"{flag}{ROLLOUT_USER_PERCENT_SUFFIX}": "101"},
                user_id="user-one",
            )
        )
        self.assertFalse(
            pwa_rollout_allows(
                flag,
                environment={f"{flag}{ROLLOUT_USER_PERCENT_SUFFIX}": "10.5"},
                user_id="user-one",
            )
        )
        self.assertFalse(
            pwa_rollout_allows(
                flag,
                environment={f"{flag}{ROLLOUT_USER_PERCENT_SUFFIX}": "  "},
                user_id="user-one",
            )
        )
        self.assertFalse(
            pwa_rollout_allows(
                flag,
                environment={
                    f"{flag}{ROLLOUT_WORKSPACE_PERCENT_SUFFIX}": "100",
                    f"{flag}{ROLLOUT_USER_PERCENT_SUFFIX}": "0",
                },
                user_id="user-one",
                workspace_id="workspace-one",
            )
        )

    def test_config_and_app_gate_apply_session_cohorts_without_exposing_identity(self) -> None:
        app_flag = "MAVERICK_FEATURE_PWA_APP_CACHE_WEBSITE_STUDIO"
        environment = {
            MAVERICK_FEATURE_PWA_DATA_CACHE: "1",
            app_flag: "1",
            f"{MAVERICK_FEATURE_PWA_DATA_CACHE}{ROLLOUT_USER_PERCENT_SUFFIX}": "50",
        }
        denied_user = next(
            user_id
            for user_id in (f"user-{index}" for index in range(100))
            if not pwa_rollout_allows(
                MAVERICK_FEATURE_PWA_DATA_CACHE,
                environment=environment,
                user_id=user_id,
            )
        )

        payload = public_pwa_config(environment=environment, user_id=denied_user, workspace_id="default")

        self.assertFalse(payload["features"]["data_cache"])
        self.assertFalse(
            app_data_cache_enabled(
                "website-studio",
                environment=environment,
                user_id=denied_user,
                workspace_id="default",
            )
        )
        self.assertNotIn(denied_user, str(payload))


if __name__ == "__main__":
    unittest.main()
