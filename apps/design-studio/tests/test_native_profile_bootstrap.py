"""OpenDesign native-profile bootstrap tests."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = APP_ROOT / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from native_profile_bootstrap import (  # noqa: E402
    NativeProfileBootstrap,
    bootstrap_native_profile,
    preferred_profile_id,
)


PROFILE_ID = "installed-codex-cli"


class FakeOfficialClient:
    def __init__(
        self,
        config: dict[str, object],
    ) -> None:
        self.config = copy.deepcopy(config)
        self.writes: list[dict[str, object]] = []
        self.gets: list[str] = []

    def get_json(self, path: str) -> dict[str, object]:
        self.gets.append(path)
        if path == "/api/app-config":
            return {"config": copy.deepcopy(self.config)}
        raise AssertionError(path)

    def send_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        if (method, path) != ("PUT", "/api/app-config"):
            raise AssertionError((method, path))
        self.config = copy.deepcopy(payload)
        self.writes.append(copy.deepcopy(payload))
        return {"config": copy.deepcopy(self.config)}


class NativeProfileBootstrapTests(unittest.TestCase):
    def test_replaces_unusable_cloud_selection_and_preserves_config(self) -> None:
        client = FakeOfficialClient(
            {
                "agentId": "amr",
                "onboardingCompleted": False,
                "installationId": "kept",
                "projectLocations": [{"id": "default"}],
            }
        )

        changed = bootstrap_native_profile(
            client,
            preferred_profile_id=PROFILE_ID,
        )

        self.assertTrue(changed)
        self.assertEqual(client.config["agentId"], PROFILE_ID)
        self.assertIs(client.config["onboardingCompleted"], True)
        self.assertEqual(client.config["installationId"], "kept")
        self.assertEqual(client.config["projectLocations"], [{"id": "default"}])
        self.assertEqual(len(client.writes), 1)

    def test_bootstraps_an_unset_fresh_install(self) -> None:
        client = FakeOfficialClient({})

        self.assertTrue(
            bootstrap_native_profile(client, preferred_profile_id=PROFILE_ID)
        )
        self.assertEqual(
            client.config,
            {"agentId": PROFILE_ID, "onboardingCompleted": True},
        )

    def test_preserves_an_explicit_non_cloud_agent(self) -> None:
        client = FakeOfficialClient(
            {"agentId": "installed-maverick-api", "onboardingCompleted": True}
        )

        changed = bootstrap_native_profile(
            client,
            preferred_profile_id=PROFILE_ID,
        )

        self.assertFalse(changed)
        self.assertEqual(client.gets, ["/api/app-config"])
        self.assertEqual(client.writes, [])

    def test_process_bootstrap_is_idempotent_after_success(self) -> None:
        client = FakeOfficialClient({"agentId": "amr"})
        bootstrap = NativeProfileBootstrap(
            client,
            preferred_profile_id=PROFILE_ID,
        )

        self.assertTrue(bootstrap.ensure())
        self.assertTrue(bootstrap.ensure())
        self.assertEqual(len(client.writes), 1)

    def test_prefers_cli_then_falls_back_to_api_profile(self) -> None:
        self.assertEqual(
            preferred_profile_id(
                {
                    "profiles": {
                        "profile_id": PROFILE_ID,
                        "api_profile_id": "installed-maverick-api",
                    }
                }
            ),
            PROFILE_ID,
        )
        self.assertEqual(
            preferred_profile_id(
                {"profiles": {"api_profile_id": "installed-maverick-api"}}
            ),
            "installed-maverick-api",
        )


if __name__ == "__main__":
    unittest.main()
