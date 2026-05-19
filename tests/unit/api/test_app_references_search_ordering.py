from __future__ import annotations

import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.api.app_references_api import _search_references
from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.service import install_store_app, register_app_source_from_contract
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class AppReferenceSearchOrderingTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_search_ranks_matching_results_before_truncating_provider_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app, cookie = self._install_search_apps(
                self._repo_root(temp_dir),
                late_labels=["folder test"],
            )

            status, payload, _headers = self._invoke(
                app,
                path="/api/app-references/search",
                method="POST",
                body={"query": "folder test", "limit": 3},
                cookie=cookie,
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["app_id"], "late-storage")
        self.assertEqual(payload["items"][0]["label"], "folder test")

    def test_empty_search_interleaves_reference_providers_before_truncating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app, cookie = self._install_search_apps(
                self._repo_root(temp_dir),
                late_labels=["Storage folder"],
            )

            status, payload, _headers = self._invoke(
                app,
                path="/api/app-references/search",
                method="POST",
                body={"query": "", "limit": 2},
                cookie=cookie,
            )

        self.assertEqual(status, 200)
        self.assertEqual({item["app_id"] for item in payload["items"]}, {"noisy-records", "late-storage"})

    def test_generic_search_calls_reference_providers_concurrently(self) -> None:
        providers = [
            self._provider("first"),
            self._provider("second"),
        ]
        lock = threading.Lock()
        second_started = threading.Event()
        parallel_observed: list[bool] = []
        started: list[str] = []

        def fake_call_reference_tool(_state, provider, _action, **_kwargs):
            with lock:
                started.append(provider["app_id"])
                is_first_call = len(started) == 1
                if len(started) >= 2:
                    second_started.set()
            if is_first_call:
                parallel_observed.append(second_started.wait(timeout=0.25))
            return {
                "results": [
                    {
                        "entity_type": "record",
                        "entity_id": f"{provider['app_id']}-record",
                        "title": f"{provider['app_id']} record",
                    }
                ]
            }

        with (
            patch("core.api.app_references_api.reference_providers", return_value=providers),
            patch("core.api.app_references_api.mcp_context_for_request", return_value=object()),
            patch("core.api.app_references_api.call_reference_tool", side_effect=fake_call_reference_tool),
        ):
            payload = _search_references(object(), context=object(), body={"query": "", "limit": 2}, start_path=Path("."))

        self.assertTrue(parallel_observed, "first provider call was not observed")
        self.assertTrue(parallel_observed[0], "second provider did not start while first provider was still running")
        self.assertEqual([item["app_id"] for item in payload["items"]], ["first", "second"])

    def _install_search_apps(self, repo_root: Path, *, late_labels: list[str]) -> tuple[PlatformHost, str]:
        self._write_search_reference_app(
            repo_root / "apps" / "noisy-records",
            app_id="noisy-records",
            labels=[f"Generic record {index}" for index in range(1, 10)],
        )
        self._write_search_reference_app(repo_root / "apps" / "late-storage", app_id="late-storage", labels=late_labels)
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root)
        noisy_source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(repo_root / "apps" / "noisy-records"),
        )
        storage_source = register_app_source_from_contract(
            state.app_store,
            source_kind="platform",
            source_path=str(repo_root / "apps" / "late-storage"),
        )
        install_store_app(state.app_store, source_id=noisy_source.source_id, workspace_id="default", start_path=repo_root)
        install_store_app(state.app_store, source_id=storage_source.source_id, workspace_id="default", start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        return app, self._login(app)

    def _provider(self, app_id: str) -> dict[str, object]:
        return {
            "app_id": app_id,
            "public_app_id": app_id,
            "mount_app_id": app_id,
            "tool_owner_app_id": app_id,
            "name": app_id,
            "description": "",
            "entities": [
                {
                    "entity_type": "record",
                    "display_name": "Record",
                    "searchable": True,
                    "resolvable": True,
                    "summarizable": True,
                    "deep_link_supported": True,
                }
            ],
            "tools": {
                "manifest": "",
                "search": f"{app_id}_reference_search",
                "resolve": "",
                "summarize": "",
            },
        }


if __name__ == "__main__":
    unittest.main()
