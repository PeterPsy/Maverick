"""Semantic effect audit for Website Studio CLI and MCP reads."""

from __future__ import annotations

import ast
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from database import ensure_schema
from service import handle_action


READ_ACTION_ARGUMENTS: dict[str, dict[str, object]] = {
    "manifest": {},
    "sites_list": {},
    "bootstrap": {},
    "workspace_snapshot": {},
    "site_status": {},
    "git_connections_list": {},
    "environments_list": {},
    "publish_targets_list": {},
    "sitemap": {},
    "navigation_analyze": {},
    "search": {"query": "Audit"},
    "read_file": {"path": "index.html"},
    "diff": {},
    "list_changes": {},
    "builds_list": {},
    "runtime_status": {},
    "approvals_list": {},
    "active_context": {},
    "page_context": {"route": "/"},
    "reference_manifest": {},
    "reference_search": {"query": "Audit"},
    "reference_resolve": {"entity_type": "site"},
    "reference_summarize": {"entity_type": "site"},
    "view_filter": {},
}

READ_MCP_TOOL_ACTIONS = {
    "website_manifest": "manifest",
    "website_sites_list": "sites_list",
    "website_bootstrap": "bootstrap",
    "website_site_status": "site_status",
    "website_git_connections_list": "git_connections_list",
    "website_environments_list": "environments_list",
    "website_publish_targets_list": "publish_targets_list",
    "website_sitemap": "sitemap",
    "website_navigation_analyze": "navigation_analyze",
    "website_search": "search",
    "website_read_file": "read_file",
    "website_diff": "diff",
    "website_list_changes": "list_changes",
    "website_builds_list": "builds_list",
    "website_runtime_status": "runtime_status",
    "website_approvals_list": "approvals_list",
    "website_active_context": "active_context",
    "website_page_context": "page_context",
    "website_reference_manifest": "reference_manifest",
    "website_reference_search": "reference_search",
    "website_reference_resolve": "reference_resolve",
    "website_reference_summarize": "reference_summarize",
    "website_studio_reference_manifest": "reference_manifest",
    "website_studio_reference_search": "reference_search",
    "website_studio_reference_resolve": "reference_resolve",
    "website_studio_reference_summarize": "reference_summarize",
    "website_studio_view_filter": "view_filter",
}


class WebsiteStudioEffectClassificationTest(unittest.TestCase):
    def test_preview_preparation_is_mutating_on_cli_and_mcp(self) -> None:
        cli = json.loads(
            (APP_ROOT / "cli" / "command_schemas.json").read_text(
                encoding="utf-8"
            )
        )["commands"]["website-studio"]["effect_class_by_argument"][
            "value_effect_classes"
        ]
        mcp = json.loads(
            (APP_ROOT / "mcp" / "tool_schemas.json").read_text(
                encoding="utf-8"
            )
        )["tools"]

        for action in ("build_preview", "preview_document"):
            self.assertEqual(cli[action], "mutating")
        self.assertEqual(mcp["website_build_preview"]["effect_class"], "mutating")
        self.assertEqual(
            mcp["website_preview_document"]["effect_class"],
            "mutating",
        )

    def test_preview_preparation_changes_persistent_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            status, created = handle_action(
                data_root,
                {"action": "site_create", "display_name": "Preview Effect"},
            )
            self.assertEqual(status, 201)
            site_id = str(created["site"]["id"])

            before_preview = _persistent_state(data_root)
            status, preview = handle_action(
                data_root,
                {"action": "build_preview", "site_id": site_id, "route": "/"},
            )
            self.assertEqual(status, 200)
            after_preview = _persistent_state(data_root)
            self.assertNotEqual(after_preview, before_preview)
            self.assertEqual(_table_count(data_root, "previews"), 1)
            self.assertEqual(_table_count(data_root, "runtime_sessions"), 1)

            before_document = after_preview
            status, document = handle_action(
                data_root,
                {
                    "action": "preview_document",
                    "preview_id": preview["preview_id"],
                },
            )
            self.assertEqual(status, 200, document)
            self.assertNotEqual(_persistent_state(data_root), before_document)
            self.assertTrue(
                list(
                    (data_root / "run" / "preview-documents").glob("**/*.json")
                )
            )

    def test_every_declared_read_preserves_persistent_app_state(self) -> None:
        self._assert_schema_read_sets_match_audit()
        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            status, created = handle_action(
                data_root,
                {"action": "site_create", "display_name": "Effect Audit"},
            )
            self.assertEqual(status, 201)
            site_id = str(created["site"]["id"])
            with closing(sqlite3.connect(data_root / "app.sqlite")) as database:
                database.execute("DELETE FROM environments WHERE site_id = ?", (site_id,))
                database.execute("DELETE FROM project_read_models WHERE site_id = ?", (site_id,))
                database.execute(
                    "UPDATE sites SET source_profile_json = '{}', source_version = '' "
                    "WHERE id = ?",
                    (site_id,),
                )
                database.commit()

            for action, raw_arguments in READ_ACTION_ARGUMENTS.items():
                with self.subTest(action=action):
                    arguments = {
                        "action": action,
                        **raw_arguments,
                    }
                    if action not in {"manifest", "sites_list", "view_filter"}:
                        arguments.setdefault("site_id", site_id)
                    if action in {"reference_resolve", "reference_summarize"}:
                        arguments["id"] = site_id
                    before = _persistent_state(data_root)
                    result_status, result = handle_action(data_root, arguments)
                    self.assertLess(result_status, 400, result)
                    self.assertEqual(_persistent_state(data_root), before)

    def _assert_schema_read_sets_match_audit(self) -> None:
        cli = json.loads(
            (APP_ROOT / "cli" / "command_schemas.json").read_text(
                encoding="utf-8"
            )
        )["commands"]["website-studio"]["effect_class_by_argument"][
            "value_effect_classes"
        ]
        mcp = json.loads(
            (APP_ROOT / "mcp" / "tool_schemas.json").read_text(
                encoding="utf-8"
            )
        )["tools"]
        self.assertEqual(
            {action for action, effect in cli.items() if effect == "read"},
            set(READ_ACTION_ARGUMENTS),
        )
        self.assertEqual(
            {name for name, definition in mcp.items() if definition["effect_class"] == "read"},
            set(READ_MCP_TOOL_ACTIONS),
        )
        self.assertEqual(
            {
                name: action
                for name, action in _mcp_tool_actions().items()
                if name in READ_MCP_TOOL_ACTIONS
            },
            READ_MCP_TOOL_ACTIONS,
        )
        self.assertLessEqual(set(READ_MCP_TOOL_ACTIONS.values()), set(READ_ACTION_ARGUMENTS))


def _persistent_state(data_root: Path) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    ensure_schema(data_root)
    with closing(sqlite3.connect(data_root / "app.sqlite")) as database:
        database_dump = tuple(database.iterdump())
    files: list[tuple[str, str]] = []
    for path in sorted(data_root.rglob("*")):
        if not path.is_file() or path.name.startswith("app.sqlite"):
            continue
        files.append(
            (
                path.relative_to(data_root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return database_dump, tuple(files)


def _table_count(data_root: Path, table: str) -> int:
    with closing(sqlite3.connect(data_root / "app.sqlite")) as database:
        return int(database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _mcp_tool_actions() -> dict[str, str]:
    tree = ast.parse((APP_ROOT / "mcp" / "server.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "TOOL_ACTIONS"
            for target in node.targets
        ):
            payload = ast.literal_eval(node.value)
            if isinstance(payload, dict):
                return {str(key): str(value) for key, value in payload.items()}
    raise AssertionError("Website Studio MCP TOOL_ACTIONS mapping not found")


if __name__ == "__main__":
    unittest.main()
