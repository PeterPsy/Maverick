"""Service tests for Docs Studio."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from core.app_sdk.runtime import AppEntrypointPayload

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from service import (
    create_page,
    default_state,
    docs_manifest,
    docs_read,
    docs_search,
    load_state,
    set_view_filter,
    state_payload,
    update_page,
    view_filter,
)
from app_readmes import build_apps_section


class DocsStudioServiceTest(unittest.TestCase):
    def _payload(self, data_root: str) -> AppEntrypointPayload:
        return AppEntrypointPayload(
            raw={},
            app_id="docs-studio",
            workspace_id="default",
            data_root=data_root,
            workspace_root=None,
            body={},
            arguments={},
        )

    def test_default_state_is_lightweight_configuration(self) -> None:
        state = default_state()
        self.assertEqual(state["schema_version"], "1")
        self.assertIn("site", state)
        self.assertNotIn("sections", state)

    def test_create_and_update_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._payload(tmp)
            created = create_page(payload, {"section_id": "getting-started", "title": "Install"})
            page = created["page"]
            self.assertEqual(page["title"], "Install")

            updated = update_page(payload, {"page_id": page["id"], "summary": "Install the product."})
            self.assertEqual(updated["page"]["summary"], "Install the product.")
            persisted = load_state(payload)
            self.assertTrue(Path(tmp, "state.json").exists())
            self.assertEqual(persisted["schema_version"], "1")
            self.assertNotIn("sections", persisted)
            self.assertTrue(Path(tmp, "pages", "manifest.json").exists())

    def test_state_payload_composes_apps_without_persisting_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._payload(tmp)
            response = state_payload(payload)
            sections = response["state"]["sections"]
            apps_section = next(section for section in sections if section["id"] == "apps")
            self.assertGreater(len(apps_section["pages"]), 0)
            self.assertGreater(sum(len(section["pages"]) for section in sections), len(apps_section["pages"]))
            persisted = load_state(payload)
            self.assertNotIn("sections", persisted)

    def test_docs_manifest_is_compact_and_filterable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._payload(tmp)
            response = docs_manifest(payload, {"section_id": "core-architecture"})
            manifest = response["manifest"]
            self.assertEqual(manifest["section_count"], 1)
            self.assertGreater(manifest["page_count"], 0)
            page = manifest["sections"][0]["pages"][0]
            self.assertIn("page_id", page)
            self.assertNotIn("body", page)

    def test_docs_search_and_read_target_single_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._payload(tmp)
            results = docs_search(payload, {"query": "provider credentials", "limit": 3})["results"]
            self.assertTrue(results)
            self.assertLessEqual(len(results), 3)
            self.assertIn("excerpt", results[0])

            page = docs_read(payload, {"page_id": results[0]["page_id"], "max_chars": 900})["page"]
            self.assertIsNotNone(page)
            self.assertEqual(page["body_format"], "markdown")
            self.assertIn("body", page)
            self.assertLessEqual(len(page["body"]), 900)

    def test_docs_search_filters_app_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._payload(tmp)
            results = docs_search(
                payload,
                {"query": "Docs Studio", "section_id": "apps", "source_app_id": "docs-studio", "limit": 5},
            )["results"]
            self.assertTrue(results)
            self.assertTrue(all(result["section_id"] == "apps" for result in results))
            self.assertTrue(all(result["source_app_id"] == "docs-studio" for result in results))

    def test_view_filter_persists_sidebar_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._payload(tmp)
            updated = set_view_filter(payload, {"query": "provider", "section_id": "providers"})

            self.assertEqual(updated["view_state"]["query"], "provider")
            self.assertEqual(updated["view_state"]["section_id"], "providers")
            self.assertEqual(view_filter(payload)["view_state"]["query"], "provider")
            persisted = load_state(payload)
            self.assertNotIn("sections", persisted)

    def test_app_docs_deduplicate_identical_readmes_across_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "maverick"
            workspace_root = repo_root / "workspaces" / "default"
            workspace_app = workspace_root / "apps" / "sample-app"
            server_app = repo_root / "apps" / "sample-app"
            for app_root, mode, access in (
                (workspace_app, "workspace_local", "editable"),
                (server_app, "source_available", "forkable"),
            ):
                app_root.mkdir(parents=True)
                (app_root / "README.md").write_text("# Sample App\n\nSame docs.\n", encoding="utf-8")
                (app_root / "app_contract.json").write_text(
                    (
                        "{\n"
                        '  "app_id": "sample-app",\n'
                        '  "name": "Sample App",\n'
                        '  "version": "0.1.0",\n'
                        '  "description": "Sample app.",\n'
                        f'  "distribution": {{"mode": "{mode}", "source_access": "{access}"}}\n'
                        "}\n"
                    ),
                    encoding="utf-8",
                )

            section = build_apps_section(workspace_root)
            page = next(item for item in section["pages"] if item["id"] == "app-sample-app")

            self.assertEqual(page["body"].count("# Sample App"), 2)
            self.assertIn("## README (workspace + server)", page["body"])
            self.assertNotIn("## README (workspace)\n", page["body"])
            self.assertNotIn("## README (server)\n", page["body"])


if __name__ == "__main__":
    unittest.main()
