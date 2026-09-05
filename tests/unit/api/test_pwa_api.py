from __future__ import annotations

import json
import unittest

from core.api.pwa_api import handle_pwa_api
from core.pwa.feature_flags import (
    MAVERICK_FEATURE_PWA_DATA_CACHE,
    MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2,
)
from core.pwa.rollout import ROLLOUT_USER_PERCENT_SUFFIX


class PwaApiTests(unittest.TestCase):
    def test_config_is_public_no_store_and_reflects_live_kill_switch(self) -> None:
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(
            handle_pwa_api(
                {"PATH_INFO": "/api/pwa/config", "REQUEST_METHOD": "GET"},
                start_response,
                environment={MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2: "off"},
            )
            or []
        )

        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(captured["headers"]["Cache-Control"], "no-store")
        payload = json.loads(body)
        self.assertEqual(payload["schema"], "maverick.pwa-config.v2")
        self.assertFalse(payload["service_worker"]["enabled"])
        self.assertEqual(payload["features"], {"data_cache": False, "storage_file_cache": False})

    def test_config_rejects_mutation_methods(self) -> None:
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status
            captured["headers"] = dict(headers)

        handle_pwa_api(
            {"PATH_INFO": "/api/pwa/config", "REQUEST_METHOD": "POST"},
            start_response,
            environment={},
        )

        self.assertEqual(captured["status"], "405 Method Not Allowed")
        self.assertEqual(captured["headers"]["Allow"], "GET")

    def test_config_applies_but_never_discloses_session_cohort_keys(self) -> None:
        captured: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            captured["status"] = status

        body = b"".join(
            handle_pwa_api(
                {"PATH_INFO": "/api/pwa/config", "REQUEST_METHOD": "GET"},
                start_response,
                environment={
                    MAVERICK_FEATURE_PWA_DATA_CACHE: "1",
                    f"{MAVERICK_FEATURE_PWA_DATA_CACHE}{ROLLOUT_USER_PERCENT_SUFFIX}": "0",
                },
                user_id="sensitive-user-id",
                workspace_id="sensitive-workspace-id",
            )
            or []
        )

        self.assertEqual(captured["status"], "200 OK")
        payload = json.loads(body)
        self.assertFalse(payload["features"]["data_cache"])
        self.assertNotIn("sensitive", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
