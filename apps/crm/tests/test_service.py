"""CRM service smoke tests."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from service import app_events_for_action, handle_action
from errors import ValidationError


class CrmServiceTest(unittest.TestCase):
    def test_create_account_contact_deal_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Acme", "domain": "acme.example"})
            account_id = account_payload["account"]["id"]
            _, contact_payload = handle_action(temporary_dir, "crm.create_contact", {"display_name": "Ada Lovelace", "email": "ada@example.com", "account_id": account_id})
            self.assertEqual(contact_payload["contact"]["account_id"], account_id)
            _, deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Pilot", "account_id": account_id, "value": 12000, "stage_id": "lead"})
            deal_id = deal_payload["deal"]["id"]
            _, moved_payload = handle_action(temporary_dir, "crm.move_deal", {"id": deal_id, "stage_id": "proposal"})
            self.assertEqual(moved_payload["deal"]["stage_id"], "proposal")
            _, summary = handle_action(temporary_dir, "crm.summarize_account", {"account_id": account_id})
            self.assertEqual(summary["account"]["name"], "Acme")
            self.assertEqual(len(summary["contacts"]), 1)
            self.assertEqual(len(summary["deals"]), 1)

    def test_import_preview_and_commit_contacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            csv_payload = {"entity_type": "contact", "csv": "display_name,email\nGrace Hopper,grace@example.com\n"}
            _, preview = handle_action(temporary_dir, "crm.import_preview", csv_payload)
            self.assertEqual(preview["row_count"], 1)
            _, committed = handle_action(temporary_dir, "crm.import_commit", csv_payload)
            self.assertEqual(committed["created_count"], 1)
            _, bootstrap = handle_action(temporary_dir, "bootstrap", {})
            self.assertEqual(len(bootstrap["contacts"]), 1)

    def test_export_payload_imports_into_fresh_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            _, account_payload = handle_action(source_dir, "crm.create_account", {"name": "Acme"})
            account_id = account_payload["account"]["id"]
            _, task_payload = handle_action(source_dir, "crm.create_task", {"title": "Follow up", "account_id": account_id})
            _, note_payload = handle_action(source_dir, "crm.create_note", {"body": "Discovery notes", "account_id": account_id})
            _, export_result = handle_action(source_dir, "crm.export", {})

            _, preview = handle_action(target_dir, "crm.import_preview", export_result["export"])
            self.assertEqual(preview["counts"]["accounts"], 1)
            self.assertEqual(preview["counts"]["tasks"], 1)
            self.assertEqual(preview["counts"]["notes"], 1)

            _, imported = handle_action(target_dir, "crm.import_commit", export_result)
            self.assertEqual(imported["created_count"], 3)
            _, bootstrap = handle_action(target_dir, "bootstrap", {})
            self.assertEqual(bootstrap["accounts"][0]["id"], account_id)
            self.assertEqual(bootstrap["tasks"][0]["id"], task_payload["task"]["id"])
            self.assertEqual(bootstrap["notes"][0]["id"], note_payload["note"]["id"])

    def test_task_note_crud_search_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, task_payload = handle_action(temporary_dir, "crm.create_task", {"title": "Renewal call", "priority": "high"})
            task_id = task_payload["task"]["id"]
            _, updated_task = handle_action(temporary_dir, "crm.update_task", {"id": task_id, "status": "done"})
            self.assertEqual(updated_task["task"]["status"], "done")

            _, note_payload = handle_action(temporary_dir, "crm.create_note", {"body": "Renewal budget confirmed"})
            note_id = note_payload["note"]["id"]
            _, updated_note = handle_action(temporary_dir, "crm.update_note", {"id": note_id, "body": "Renewal budget approved"})
            self.assertEqual(updated_note["note"]["body"], "Renewal budget approved")

            _, search_result = handle_action(temporary_dir, "crm.search", {"query": "Renewal", "entity_type": "all"})
            self.assertEqual({item["entity_type"] for item in search_result["results"]}, {"task", "note"})

            _, reference_result = handle_action(temporary_dir, "references.search", {"entity_type": "task", "query": ""})
            self.assertEqual(reference_result["results"][0]["entity_type"], "task")
            self.assertEqual(reference_result["results"][0]["app_page"], f"tasks/{task_id}")

    def test_validation_errors_are_predictable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaises(ValidationError):
                handle_action(temporary_dir, "crm.create_deal", {"name": "Bad stage", "stage_id": "missing"})

            payload = {"id": "acct_duplicate", "name": "Acme"}
            handle_action(temporary_dir, "crm.create_account", payload)
            with self.assertRaises(ValidationError):
                handle_action(temporary_dir, "crm.create_account", payload)

    def test_alias_write_actions_emit_app_events(self) -> None:
        self.assertEqual(app_events_for_action("create_task")[0]["resource"], "records")
        self.assertEqual(app_events_for_action("import_commit")[0]["resource"], "records")
        self.assertEqual(app_events_for_action("set_view_filter")[0]["resource"], "view-state")

    def test_operations_manifest_lists_published_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, manifest = handle_action(temporary_dir, "operations.manifest", {})
            self.assertIn("crm.export", manifest["actions"])
            self.assertIn("crm.view_filter", manifest["actions"])
            self.assertIn("crm.set_custom_view", manifest["actions"])
            self.assertIn("crm.clear_custom_view", manifest["actions"])

    def test_bootstrap_includes_view_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            handle_action(temporary_dir, "set_custom_view", {"title": "Focus", "refs": [{"entity_type": "account", "entity_id": "account:acct_1"}]})
            _, bootstrap = handle_action(temporary_dir, "bootstrap", {})
            self.assertEqual(bootstrap["view_state"]["view_filter"]["mode"], "custom")
            self.assertEqual(bootstrap["view_state"]["view_filter"]["title"], "Focus")

    def test_set_view_filter_rejects_invalid_entity_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaises(ValidationError):
                handle_action(temporary_dir, "set_view_filter", {"entity_type": "bogus", "query": "Acme"})

    def test_bootstrap_hydrates_custom_view_refs_past_default_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            target_id = ""
            for index in range(105):
                _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": f"Account {index:03d}"})
                if index == 0:
                    target_id = account_payload["account"]["id"]

            handle_action(temporary_dir, "set_custom_view", {"title": "Late account", "refs": [{"entity_type": "account", "entity_id": f"account:{target_id}"}]})
            _, bootstrap = handle_action(temporary_dir, "bootstrap", {})
            self.assertTrue(any(account["id"] == target_id for account in bootstrap["accounts"]))


if __name__ == "__main__":
    unittest.main()
