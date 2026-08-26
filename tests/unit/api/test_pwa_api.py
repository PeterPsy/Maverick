from __future__ import annotations

import json
import unittest

from core.api.pwa_api import handle_pwa_api
from core.pwa.feature_flags import MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2


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
        self.assertFalse(json.loads(body)["service_worker"]["enabled"])

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


if __name__ == "__main__":
    unittest.main()
