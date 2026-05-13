from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
