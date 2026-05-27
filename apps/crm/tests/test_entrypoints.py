"""End-to-end smoke tests for CRM CLI and MCP entrypoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = next(parent for parent in APP_ROOT.parents if (parent / "core").is_dir())


def run_entrypoint(path: Path, payload: dict) -> dict:
    env = {**os.environ, "PYTHONPATH": str(CORE_ROOT)}
    result = subprocess.run(
        [sys.executable, str(path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    return json.loads(result.stdout)


class CrmEntrypointTest(unittest.TestCase):
    def test_cli_and_mcp_entrypoints_share_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_payload = {"app_id": "crm", "workspace_id": "test", "data_root": temporary_dir}
            cli_result = run_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                {**base_payload, "arguments": {"action": "crm.create_account", "name": "Entrypoint Account", "status": "prospect"}},
            )
            account_id = cli_result["account"]["id"]
            self.assertEqual(cli_result["status_code"], 201)

            mcp_result = run_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                {**base_payload, "tool_name": "crm_tag_record", "arguments": {"entity_type": "account", "id": account_id, "tag": "CLI-MCP"}},
            )
            self.assertEqual(mcp_result["status_code"], 200)
            self.assertEqual(mcp_result["record"]["tags"][0]["name"], "CLI-MCP")

            export_result = run_entrypoint(APP_ROOT / "mcp" / "server.py", {**base_payload, "tool_name": "crm_export", "arguments": {}})
            self.assertEqual(export_result["status_code"], 200)
            self.assertEqual(export_result["export"]["accounts"][0]["id"], account_id)

            health_result = run_entrypoint(APP_ROOT / "cli" / "app_cli.py", {**base_payload, "arguments": {"action": "crm.health"}})
            self.assertTrue(health_result["ok"])
            self.assertTrue(health_result["checks"]["export"]["ok"])

            report_result = run_entrypoint(APP_ROOT / "mcp" / "server.py", {**base_payload, "tool_name": "crm_sales_reports", "arguments": {}})
            self.assertEqual(report_result["status_code"], 200)
            self.assertIn("pipeline_value_by_stage", report_result)

            source_result = run_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                {**base_payload, "arguments": {"action": "crm.create_account", "name": "Merge Source", "industry": "Services"}},
            )
            merge_result = run_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                {**base_payload, "tool_name": "crm_merge_records", "arguments": {"entity_type": "account", "target_id": account_id, "source_id": source_result["account"]["id"]}},
            )
            self.assertEqual(merge_result["status_code"], 200)
            self.assertEqual(merge_result["target"]["industry"], "Services")

            audit_result = run_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                {**base_payload, "tool_name": "crm_audit_log", "arguments": {"entity_type": "account", "entity_id": account_id, "event_type": "record.merged"}},
            )
            self.assertEqual(audit_result["events"][0]["event_type"], "record.merged")

            run_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                {
                    **base_payload,
                    "arguments": {
                        "subcommand": "crm.create_automation_rule",
                        "name": "Entrypoint follow-up",
                        "trigger_event": "account.created",
                        "entity_type": "account",
                        "conditions": {},
                        "action": {"type": "create_task", "title": "Entrypoint task"},
                    },
                },
            )
            automation_result = run_entrypoint(
                APP_ROOT / "cli" / "app_cli.py",
                {
                    **base_payload,
                    "arguments": {
                        "subcommand": "crm.run_automation_rules",
                        "trigger_event": "account.created",
                        "entity_type": "account",
                        "entity_id": account_id,
                    },
                },
            )
            self.assertEqual(automation_result["created_count"], 1)
            self.assertEqual(automation_result["workflow_proposals"][0]["status"], "pending")

            unpublished_tool = run_entrypoint(
                APP_ROOT / "mcp" / "server.py",
                {**base_payload, "tool_name": "crm_create_automation_rule", "arguments": {}},
            )
            self.assertEqual(unpublished_tool["status_code"], 404)
            self.assertEqual(unpublished_tool["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
