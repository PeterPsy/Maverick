"""CRM service smoke tests."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from service import app_events_for_action, handle_action
from domains.records import records_table
from errors import NotFoundError, ValidationError
from store import connect, delete_fts, initialize, utc_now


class CrmServiceTest(unittest.TestCase):
    def test_website_intake_creates_lead_sends_mail_and_is_idempotent(self) -> None:
        sent: list[tuple[str, dict[str, object]]] = []

        def fake_mail_sender(provider_app_id: str, payload: dict[str, object]) -> dict[str, object]:
            sent.append((provider_app_id, payload))
            index = len(sent)
            return {
                "draft": {"id": f"mail_draft_{index}", "subject": payload["subject"]},
                "result": {"sent": True, "provider_message_id": f"provider_msg_{index}", "thread_id": f"email_thread_{index}"},
            }

        with tempfile.TemporaryDirectory() as temporary_dir:
            payload = self._website_intake_payload(
                {
                    "_mail_sender": fake_mail_sender,
                    "_app_dependencies": {"dependencies": [{"alias": "mail", "selected_provider_app_ids": ["mail"]}]},
                }
            )
            status, result = handle_action(temporary_dir, "crm.website_intake", payload)

            self.assertEqual(status, 201)
            self.assertEqual(result["email_status"], "sent")
            self.assertEqual(result["lead"]["email"], "ada@example.com")
            self.assertEqual(result["lead"]["source"], "website:onboarding")
            self.assertEqual(result["lead"]["owner_id"], "Peter.fioretti94@gmail.com")
            self.assertEqual(len(sent), 2)
            self.assertEqual(sent[0][0], "mail")
            self.assertEqual(sent[0][1]["reply_to"][0]["email"], "ada@example.com")
            self.assertIn("body_html", sent[1][1])

            duplicate_status, duplicate = handle_action(temporary_dir, "crm.website_intake", payload)
            self.assertEqual(duplicate_status, 201)
            self.assertEqual(duplicate["status"], "duplicate")
            self.assertEqual(len(sent), 2)

            with connect(temporary_dir) as db:
                intake_count = db.execute("SELECT COUNT(*) AS count FROM website_intakes").fetchone()["count"]
                outbox_rows = db.execute("SELECT kind, status FROM crm_outbox ORDER BY kind").fetchall()
                external_refs = db.execute("SELECT source_app_id, source_entity_type FROM external_refs WHERE crm_entity_type = 'lead' ORDER BY source_app_id, source_entity_type").fetchall()
            self.assertEqual(intake_count, 1)
            self.assertEqual({row["status"] for row in outbox_rows}, {"sent"})
            self.assertIn(("loopino-website", "website_intake"), {(row["source_app_id"], row["source_entity_type"]) for row in external_refs})
            self.assertIn(("mail", "email_thread"), {(row["source_app_id"], row["source_entity_type"]) for row in external_refs})

    def test_website_intake_keeps_lead_when_mail_fails(self) -> None:
        def failing_mail_sender(_provider_app_id: str, _payload: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("mail unavailable")

        with tempfile.TemporaryDirectory() as temporary_dir:
            status, result = handle_action(
                temporary_dir,
                "crm.website_intake",
                self._website_intake_payload(
                    {
                        "_mail_sender": failing_mail_sender,
                        "_app_dependencies": {"dependencies": [{"alias": "mail", "selected_provider_app_ids": ["mail"]}]},
                        "notification": {"team_email": "", "send_team": False, "send_lead": True},
                    }
                ),
            )

            self.assertEqual(status, 201)
            self.assertEqual(result["email_status"], "failed")
            self.assertEqual(result["lead"]["email"], "ada@example.com")
            with connect(temporary_dir) as db:
                outbox = db.execute("SELECT status, attempts, last_error FROM crm_outbox").fetchone()
                lead_count = db.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"]
            self.assertEqual(lead_count, 1)
            self.assertEqual(outbox["status"], "failed")
            self.assertEqual(outbox["attempts"], 1)
            self.assertIn("mail unavailable", outbox["last_error"])

    def test_website_intake_retry_failed_email_does_not_resend_sent_outbox(self) -> None:
        sent_subjects: list[str] = []

        def partially_failing_sender(_provider_app_id: str, payload: dict[str, object]) -> dict[str, object]:
            sent_subjects.append(str(payload["subject"]))
            if len(sent_subjects) == 2:
                raise RuntimeError("lead confirmation failed")
            return {"draft": {"id": "team_draft"}, "result": {"sent": True, "thread_id": "team_thread"}}

        def retry_sender(_provider_app_id: str, payload: dict[str, object]) -> dict[str, object]:
            sent_subjects.append(f"retry:{payload['subject']}")
            return {"draft": {"id": "retry_draft"}, "result": {"sent": True, "thread_id": "retry_thread"}}

        with tempfile.TemporaryDirectory() as temporary_dir:
            payload = self._website_intake_payload(
                {
                    "_mail_sender": partially_failing_sender,
                    "_app_dependencies": {"dependencies": [{"alias": "mail", "selected_provider_app_ids": ["mail"]}]},
                }
            )
            _status, result = handle_action(temporary_dir, "crm.website_intake", payload)
            self.assertEqual(result["email_status"], "partial_failed")

            retry_payload = {**payload, "_mail_sender": retry_sender, "retry_failed_email": True}
            _retry_status, retry_result = handle_action(temporary_dir, "crm.website_intake", retry_payload)

            self.assertEqual(retry_result["email_status"], "sent")
            self.assertEqual(sent_subjects.count("[Loopino intake] Onboarding backup - Email - ada@example.com"), 1)
            self.assertIn("retry:Richiesta ricevuta | Loopino", sent_subjects)

    def test_website_intake_records_outbox_failure_when_mail_provider_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            status, result = handle_action(
                temporary_dir,
                "crm.website_intake",
                self._website_intake_payload({"_app_dependencies": {"dependencies": []}, "_maverick_command": "/bin/false"}),
            )

            self.assertEqual(status, 201)
            self.assertEqual(result["email_status"], "failed")
            self.assertTrue(result["outbox"])
            self.assertEqual({item["status"] for item in result["outbox"]}, {"failed"})
            self.assertTrue(all("no selected provider" in item["last_error"] for item in result["outbox"]))
            with connect(temporary_dir) as db:
                lead_count = db.execute("SELECT COUNT(*) AS count FROM leads").fetchone()["count"]
                outbox_count = db.execute("SELECT COUNT(*) AS count FROM crm_outbox").fetchone()["count"]
            self.assertEqual(lead_count, 1)
            self.assertEqual(outbox_count, 2)

    def test_initialize_migrates_external_ref_provider_columns_before_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / "crm.sqlite"
            db = sqlite3.connect(db_path)
            db.executescript(
                """
                CREATE TABLE schema_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO schema_metadata(key, value) VALUES ('schema_version', '4');
                CREATE TABLE external_refs (
                  id TEXT PRIMARY KEY,
                  crm_entity_type TEXT NOT NULL,
                  crm_entity_id TEXT NOT NULL,
                  source_app_id TEXT NOT NULL,
                  source_entity_type TEXT NOT NULL,
                  source_entity_id TEXT NOT NULL,
                  link_type TEXT NOT NULL DEFAULT 'related',
                  title TEXT NOT NULL DEFAULT '',
                  summary TEXT NOT NULL DEFAULT '',
                  occurred_at TEXT NOT NULL DEFAULT '',
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  deleted_at TEXT
                );
                """
            )
            db.close()

            initialize(temporary_dir)

            with connect(temporary_dir) as migrated:
                columns = {row["name"] for row in migrated.execute("PRAGMA table_info(external_refs)")}
                indexes = {row["name"] for row in migrated.execute("PRAGMA index_list(external_refs)")}
            self.assertIn("provider_alias", columns)
            self.assertIn("source_interface", columns)
            self.assertIn("normalized_link_type", columns)
            self.assertIn("idx_external_refs_provider", indexes)

    def _website_intake_payload(self, extra: dict[str, object] | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "submission_id": "intake_20260529_test",
            "received_at": "2026-05-29T10:00:00+00:00",
            "source": "onboarding",
            "contact": {
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "phone": "+39 123",
                "company": "Analytical Engines",
                "website": "https://www.ada.example",
            },
            "request": {
                "type": "demo",
                "service_interest": "maverick",
                "primary_goal": "Vedere Maverick sul processo commerciale.",
                "preferred_contact": "email",
                "urgency": "30-days",
                "team_size": "2-10",
            },
            "answers": {"challenge_summary": "Follow-up manuali", "ricontatto_slot": "martedi mattina"},
            "source_context": {"source_path": "/product/maverick/", "entry_label": "Demo Maverick"},
            "notification": {"team_email": "team@loopino.ai", "send_team": True, "send_lead": True},
        }
        if extra:
            payload.update(extra)
        return payload

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

    def test_lead_conversion_creates_related_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, lead_payload = handle_action(
                temporary_dir,
                "crm.create_lead",
                {"display_name": "Nora Lead", "email": "nora@example.com", "company": "Nora Co", "domain": "nora.example"},
            )
            lead_id = lead_payload["lead"]["id"]

            _, converted = handle_action(temporary_dir, "crm.convert_lead", {"lead_id": lead_id, "deal_name": "Nora pilot", "value": 5000})

            self.assertTrue(converted["ok"])
            self.assertEqual(converted["lead"]["status"], "converted")
            self.assertEqual(converted["account"]["name"], "Nora Co")
            self.assertEqual(converted["contact"]["email"], "nora@example.com")
            self.assertEqual(converted["deal"]["stage_id"], "qualified")

    def test_pipeline_stage_configuration_and_drag_target_move(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, stage = handle_action(temporary_dir, "crm.create_pipeline_stage", {"name": "Negotiation", "position": 35, "probability": 0.7})
            _, deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Configurable stage deal"})
            deal_id = deal_payload["deal"]["id"]

            _, moved = handle_action(temporary_dir, "crm.move_deal", {"id": deal_id, "stage_id": stage["stage"]["id"]})
            self.assertEqual(moved["deal"]["stage"], "Negotiation")
            self.assertEqual(moved["deal"]["probability"], 0.7)

            _, renamed = handle_action(temporary_dir, "crm.update_pipeline_stage", {"id": stage["stage"]["id"], "name": "Contracting", "position": 35, "probability": 0.75})
            self.assertEqual(renamed["stage"]["name"], "Contracting")
            _, refreshed = handle_action(temporary_dir, "crm.get_record", {"entity_type": "deal", "id": deal_id})
            self.assertEqual(refreshed["record"]["stage"], "Contracting")

    def test_pipeline_stage_delete_moves_deals_to_replacement_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, used_stage = handle_action(temporary_dir, "crm.create_pipeline_stage", {"name": "Used", "position": 25, "probability": 0.8})
            _, deal = handle_action(temporary_dir, "crm.create_deal", {"name": "Used stage deal", "stage_id": used_stage["stage"]["id"]})

            _, deleted = handle_action(temporary_dir, "crm.delete_pipeline_stage", {"id": used_stage["stage"]["id"]})
            self.assertTrue(deleted["ok"])
            self.assertEqual(deleted["stage"]["name"], "Used")
            self.assertEqual(deleted["replacement_stage"]["id"], "qualified")
            self.assertEqual(deleted["moved_deal_count"], 1)
            _, refreshed = handle_action(temporary_dir, "crm.get_record", {"entity_type": "deal", "id": deal["deal"]["id"]})
            self.assertEqual(refreshed["record"]["stage_id"], "qualified")
            self.assertEqual(refreshed["record"]["stage"], "Qualified")
            _, board = handle_action(temporary_dir, "crm.pipeline_board", {})
            self.assertFalse(any(stage["id"] == used_stage["stage"]["id"] for stage in board["stages"]))

    def test_pipeline_board_returns_all_deals_past_bootstrap_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Board Account"})
            account_id = account_payload["account"]["id"]
            _, contact_payload = handle_action(temporary_dir, "crm.create_contact", {"display_name": "Board Contact", "account_id": account_id})
            contact_id = contact_payload["contact"]["id"]
            for index in range(125):
                handle_action(
                    temporary_dir,
                    "crm.create_deal",
                    {
                        "name": f"Board Deal {index:03d}",
                        "account_id": account_id,
                        "contact_id": contact_id,
                        "value": 100 + index,
                        "stage_id": "lead",
                    },
                )

            _, bootstrap = handle_action(temporary_dir, "bootstrap", {})
            _, board = handle_action(temporary_dir, "crm.pipeline_board", {})
            lead_stage = next(stage for stage in board["stages"] if stage["id"] == "lead")

            self.assertEqual(len(bootstrap["deals"]), 100)
            self.assertEqual(board["totals"]["deal_count"], 125)
            self.assertEqual(lead_stage["deal_count"], 125)
            self.assertEqual(len(lead_stage["deals"]), 125)
            self.assertEqual(lead_stage["deals"][0]["account_label"], "Board Account")
            self.assertEqual(lead_stage["deals"][0]["contact_label"], "Board Contact")
            self.assertIn(lead_stage["deals"][0]["health"]["status"], {"active", "stuck", "past_due"})

    def test_timeline_saved_view_bulk_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Acme", "domain": "dup.example"})
            account_id = account_payload["account"]["id"]
            _, second_account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Acme EU", "domain": "dup.example", "owner_id": "owner_eu"})
            second_account_id = second_account_payload["account"]["id"]
            handle_action(temporary_dir, "crm.create_contact", {"display_name": "Ada A", "email": "ada@example.com", "account_id": account_id})
            _, contact_payload = handle_action(temporary_dir, "crm.create_contact", {"display_name": "Ada B", "email": "ada@example.com", "account_id": account_id})
            contact_id = contact_payload["contact"]["id"]
            handle_action(temporary_dir, "crm.create_note", {"body": "Important account note", "account_id": account_id})
            handle_action(temporary_dir, "crm.create_task", {"title": "Call Ada", "contact_id": contact_id})

            _, timeline = handle_action(temporary_dir, "crm.timeline", {"entity_type": "account", "id": account_id})
            self.assertGreaterEqual(len(timeline["items"]), 2)

            _, saved = handle_action(temporary_dir, "crm.save_view", {"title": "Tagged accounts", "entity_type": "account", "query": "Acme", "filters": {"tag": "Focus"}})
            _, listed = handle_action(temporary_dir, "crm.list_saved_views", {})
            self.assertEqual(listed["saved_views"][0]["id"], saved["saved_view"]["id"])

            _, bulk = handle_action(temporary_dir, "crm.bulk_update", {"entity_type": "account", "ids": [account_id], "operation": "tag", "tag": "Focus"})
            self.assertEqual(bulk["updated_count"], 1)
            _, filtered = handle_action(temporary_dir, "crm.filter_records", {"entity_type": "account", "filters": {"tag": "Focus"}})
            self.assertEqual(filtered["records"][0]["id"], account_id)
            handle_action(temporary_dir, "crm.define_custom_field", {"entity_type": "account", "field_key": "segment", "label": "Segment"})
            handle_action(temporary_dir, "crm.set_custom_fields", {"entity_type": "account", "id": second_account_id, "custom_fields": {"segment": "EMEA"}})

            _, duplicates = handle_action(temporary_dir, "crm.find_duplicates", {})
            duplicate_keys = {(group["entity_type"], group["field"]) for group in duplicates["groups"]}
            self.assertIn(("account", "domain"), duplicate_keys)
            self.assertIn(("contact", "email"), duplicate_keys)
            account_group = next(group for group in duplicates["groups"] if group["entity_type"] == "account" and group["field"] == "domain")
            self.assertEqual({record["id"] for record in account_group["records"]}, {account_id, second_account_id})
            account_records = {record["id"]: record for record in account_group["records"]}
            self.assertEqual(account_records[account_id]["tags"][0]["name"], "Focus")
            self.assertEqual(account_records[second_account_id]["owner_id"], "owner_eu")
            self.assertEqual(account_records[second_account_id]["custom_fields"]["segment"], "EMEA")

    def test_external_refs_link_timeline_unlink_and_health(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Linked Account"})
            account_id = account_payload["account"]["id"]

            _, linked = handle_action(
                temporary_dir,
                "crm.link_external_ref",
                {
                    "crm_entity_type": "account",
                    "crm_entity_id": account_id,
                    "source_app_id": "mail",
                    "source_entity_type": "thread",
                    "source_entity_id": "thread_1",
                    "link_type": "email_thread",
                    "title": "Intro thread",
                    "summary": "Initial conversation",
                    "occurred_at": "2026-05-20T10:00:00+00:00",
                },
            )
            ref_id = linked["external_ref"]["id"]

            _, listed = handle_action(temporary_dir, "crm.list_external_refs", {"crm_entity_type": "account", "crm_entity_id": account_id})
            self.assertEqual(listed["external_refs"][0]["source_app_id"], "mail")

            _, timeline = handle_action(temporary_dir, "crm.timeline", {"entity_type": "account", "id": account_id})
            external_items = [item for item in timeline["items"] if item.get("entity_type") == "external_ref"]
            self.assertEqual(external_items[0]["id"], ref_id)
            self.assertEqual(external_items[0]["ref"]["entity_id"], "thread_1")

            _, external_timeline = handle_action(temporary_dir, "crm.external_timeline", {"entity_type": "account", "id": account_id})
            self.assertEqual([item["id"] for item in external_timeline["items"]], [ref_id])

            _, health = handle_action(temporary_dir, "crm.health", {})
            self.assertTrue(health["ok"])
            self.assertEqual(health["checks"]["external_refs"]["unresolved_count"], 1)
            self.assertEqual(health["checks"]["external_refs"]["unresolved"][0]["status"], "unresolved")

            _, unlinked = handle_action(temporary_dir, "crm.unlink_external_ref", {"id": ref_id})
            self.assertTrue(unlinked["ok"])
            _, after_unlink = handle_action(temporary_dir, "crm.list_external_refs", {"crm_entity_type": "account", "crm_entity_id": account_id})
            self.assertEqual(after_unlink["external_refs"], [])

    def test_external_refs_export_import_and_malformed_health(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            _, account_payload = handle_action(source_dir, "crm.create_account", {"id": "acct_linked", "name": "Linked Account"})
            handle_action(
                source_dir,
                "crm.link_external_ref",
                {
                    "crm_entity_type": "account",
                    "crm_entity_id": account_payload["account"]["id"],
                    "source_app_id": "calendar",
                    "source_entity_type": "event",
                    "source_entity_id": "event_1",
                    "title": "Discovery call",
                    "occurred_at": "2026-05-21T09:00:00+00:00",
                },
            )
            _, export_result = handle_action(source_dir, "crm.export", {})
            self.assertEqual(export_result["export"]["external_refs"][0]["source_app_id"], "calendar")

            _, imported = handle_action(target_dir, "crm.import_commit", export_result)
            self.assertTrue(imported["ok"])
            _, restored = handle_action(target_dir, "crm.list_external_refs", {"crm_entity_type": "account", "crm_entity_id": "acct_linked"})
            self.assertEqual(restored["external_refs"][0]["source_entity_id"], "event_1")

            now = utc_now()
            with connect(target_dir) as db:
                db.execute(
                    """
                    INSERT INTO external_refs(id, crm_entity_type, crm_entity_id, source_app_id, source_entity_type, source_entity_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("xref_bad", "account", "acct_missing", "", "thread", "thread_2", now, now),
                )
            _, health = handle_action(target_dir, "crm.health", {})
            self.assertFalse(health["ok"])
            self.assertEqual(health["checks"]["external_refs"]["malformed_count"], 1)

    def test_external_ref_provider_normalization_supports_alternate_apps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, lead_payload = handle_action(temporary_dir, "crm.create_lead", {"display_name": "Provider Lead", "email": "provider@example.com"})
            lead_id = lead_payload["lead"]["id"]
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Provider Account"})
            account_id = account_payload["account"]["id"]
            _, deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Provider Deal", "account_id": account_id, "value": 12000, "stage_id": "proposal"})
            deal_id = deal_payload["deal"]["id"]

            _, mail_link = handle_action(
                temporary_dir,
                "crm.link_external_ref",
                {
                    "crm_entity_type": "lead",
                    "crm_entity_id": lead_id,
                    "source_app_id": "postbox",
                    "source_entity_type": "message",
                    "source_entity_id": "msg_1",
                    "provider_alias": "mail",
                    "link_type": "related",
                },
            )
            handle_action(
                temporary_dir,
                "crm.link_external_ref",
                {
                    "crm_entity_type": "deal",
                    "crm_entity_id": deal_id,
                    "source_app_id": "meeting-maker",
                    "source_entity_type": "booking",
                    "source_entity_id": "booking_1",
                    "source_interface": "calendar.events",
                    "link_type": "related",
                    "occurred_at": "2999-05-30T10:00:00+00:00",
                },
            )
            handle_action(
                temporary_dir,
                "crm.link_external_ref",
                {
                    "crm_entity_type": "deal",
                    "crm_entity_id": deal_id,
                    "source_app_id": "drivebox",
                    "source_entity_type": "asset",
                    "source_entity_id": "asset_1",
                    "link_type": "related",
                    "metadata": {"source_interface": "file.catalog"},
                },
            )

            self.assertEqual(mail_link["external_ref"]["provider_alias"], "mail")
            self.assertEqual(mail_link["external_ref"]["source_interface"], "mail.message")
            self.assertEqual(mail_link["external_ref"]["metadata"]["provider_alias"], "mail")

            _, detail_refs = handle_action(temporary_dir, "crm.external_timeline", {"entity_type": "deal", "id": deal_id})
            self.assertEqual(detail_refs["connection_summary"]["calendar_count"], 1)
            self.assertEqual(detail_refs["connection_summary"]["file_count"], 1)

            _, reports = handle_action(temporary_dir, "crm.sales_reports", {})
            self.assertEqual(reports["connection_metrics"]["leads_with_linked_email"], 1)
            self.assertEqual(reports["connection_metrics"]["deals_with_scheduled_call"], 1)
            self.assertEqual(reports["connection_metrics"]["pipeline_value_with_next_call"], {"EUR": 12000.0})

    def test_import_mapping_reports_row_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            csv_payload = {
                "entity_type": "lead",
                "csv": "Full Name,Email,Company\nMapped Lead,mapped@example.com,Mapped Co\n, ,Broken Co\n",
                "column_mapping": {"Full Name": "display_name", "Email": "email", "Company": "company"},
            }
            _, preview = handle_action(temporary_dir, "crm.import_preview", csv_payload)
            self.assertFalse(preview["ok"])
            self.assertEqual(preview["errors"][0]["row"], 2)

            fixed_payload = {**csv_payload, "csv": "Full Name,Email,Company\nMapped Lead,mapped@example.com,Mapped Co\n"}
            _, committed = handle_action(temporary_dir, "crm.import_commit", fixed_payload)
            self.assertTrue(committed["ok"])
            self.assertEqual(committed["records"][0]["display_name"], "Mapped Lead")

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

    def test_export_import_preserves_archived_records_and_custom_values(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            handle_action(source_dir, "crm.define_custom_field", {"entity_type": "account", "field_key": "segment", "label": "Segment"})
            _, active_payload = handle_action(source_dir, "crm.create_account", {"id": "acct_active", "name": "Active Account"})
            _, archived_payload = handle_action(source_dir, "crm.create_account", {"id": "acct_archived", "name": "Archived Account"})
            _, deleted_payload = handle_action(source_dir, "crm.create_account", {"id": "acct_deleted", "name": "Deleted Account"})
            handle_action(source_dir, "crm.set_custom_fields", {"entity_type": "account", "id": archived_payload["account"]["id"], "custom_fields": {"segment": "Dormant"}})
            handle_action(source_dir, "crm.archive_record", {"entity_type": "account", "id": archived_payload["account"]["id"]})
            handle_action(source_dir, "crm.delete_record", {"entity_type": "account", "id": deleted_payload["account"]["id"]})
            _, export_result = handle_action(source_dir, "crm.export", {})

            exported_accounts = {account["id"]: account for account in export_result["export"]["accounts"]}
            self.assertIn(active_payload["account"]["id"], exported_accounts)
            self.assertIn(archived_payload["account"]["id"], exported_accounts)
            self.assertNotIn(deleted_payload["account"]["id"], exported_accounts)
            self.assertTrue(exported_accounts[archived_payload["account"]["id"]]["archived_at"])

            handle_action(target_dir, "crm.create_account", {"id": "acct_archived", "name": "Old Archived Name"})
            handle_action(target_dir, "crm.archive_record", {"entity_type": "account", "id": "acct_archived"})
            _, imported = handle_action(target_dir, "crm.import_commit", export_result)
            self.assertTrue(imported["ok"])

            _, target_export = handle_action(target_dir, "crm.export", {})
            restored_accounts = {account["id"]: account for account in target_export["export"]["accounts"]}
            self.assertEqual(restored_accounts["acct_archived"]["name"], "Archived Account")
            self.assertEqual(restored_accounts["acct_archived"]["archived_at"], exported_accounts["acct_archived"]["archived_at"])
            self.assertEqual(restored_accounts["acct_archived"]["custom_fields"]["segment"], "Dormant")

    def test_export_includes_more_than_default_list_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            for index in range(250):
                handle_action(temporary_dir, "crm.create_account", {"name": f"Account {index:03d}"})

            _, export_result = handle_action(temporary_dir, "crm.export", {})
            self.assertEqual(len(export_result["export"]["accounts"]), 250)

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

    def test_list_next_actions_returns_only_open_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            handle_action(temporary_dir, "crm.create_task", {"title": "Open follow up", "status": "open", "due_at": "2026-05-22"})
            handle_action(temporary_dir, "crm.create_task", {"title": "Completed follow up", "status": "done", "due_at": "2026-05-21"})
            handle_action(temporary_dir, "crm.create_task", {"title": "Blocked follow up", "status": "blocked", "due_at": "2026-05-20"})

            _, result = handle_action(temporary_dir, "crm.list_next_actions", {})
            self.assertEqual([task["title"] for task in result["tasks"]], ["Open follow up"])

    def test_operations_feed_groups_tasks_workflows_and_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Ops Account", "status": "prospect"})
            account_id = account_payload["account"]["id"]
            handle_action(temporary_dir, "crm.create_task", {"title": "Call Ops Account", "status": "open", "account_id": account_id})
            handle_action(temporary_dir, "crm.create_task", {"title": "Closed Ops Account", "status": "done", "account_id": account_id})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "account", "crm_entity_id": account_id, "source_app_id": "mail", "source_entity_type": "thread", "source_entity_id": "thread_ops_1"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "account", "crm_entity_id": account_id, "source_app_id": "mail", "source_entity_type": "thread", "source_entity_id": "thread_ops_2"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "account", "crm_entity_id": account_id, "source_app_id": "calendar", "source_entity_type": "event", "source_entity_id": "event_ops"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "account", "crm_entity_id": account_id, "source_app_id": "storage", "source_entity_type": "file", "source_entity_id": "brief_ops", "link_type": "brief"})

            workflow_ids: dict[str, str] = {}
            for key, title in {
                "applied": "Apply Ops action",
                "approved": "Approved Ops action",
                "pending": "Pending Ops action",
                "dismissed": "Dismissed Ops action",
                "rejected": "Rejected Ops action",
            }.items():
                handle_action(
                    temporary_dir,
                    "crm.create_automation_rule",
                    {
                        "name": title,
                        "trigger_event": f"ops.{key}",
                        "entity_type": "account",
                        "conditions": {},
                        "action": {"type": "create_task", "title": title},
                    },
                )
                _, generated = handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": f"ops.{key}", "entity_type": "account", "entity_id": account_id})
                workflow_ids[key] = generated["workflow_proposals"][0]["id"]

            handle_action(temporary_dir, "crm.approve_workflow_proposal", {"id": workflow_ids["applied"]})
            handle_action(temporary_dir, "crm.apply_workflow_proposal", {"id": workflow_ids["applied"]})
            handle_action(temporary_dir, "crm.approve_workflow_proposal", {"id": workflow_ids["approved"]})
            handle_action(temporary_dir, "crm.dismiss_workflow_proposal", {"id": workflow_ids["dismissed"], "reason": "Not needed"})
            handle_action(temporary_dir, "crm.reject_workflow_proposal", {"id": workflow_ids["rejected"], "reason": "Bad fit"})

            _, feed = handle_action(temporary_dir, "crm.operations_feed", {"limit": 20})
            sections = {section["key"]: section for section in feed["sections"]}

            self.assertEqual(feed["counts"]["to_do"], 2)
            self.assertEqual({item["title"] for item in sections["to_do"]["items"]}, {"Call Ops Account", "Apply Ops action"})
            self.assertEqual({item["status"] for item in sections["to_approve"]["items"]}, {"pending", "approved"})
            pending_evidence = next(item["evidence"] for item in sections["to_approve"]["items"] if item["status"] == "pending")
            self.assertIn("from 2 emails", pending_evidence)
            self.assertIn("calendar event created", pending_evidence)
            self.assertIn("brief saved", pending_evidence)
            self.assertIn("requires approval", pending_evidence)
            self.assertEqual([item["ref"]["proposal_id"] for item in sections["done"]["items"]], [workflow_ids["applied"]])
            self.assertEqual({item["status"] for item in sections["discarded"]["items"]}, {"dismissed", "rejected"})
            self.assertIn("Bad fit", {item["reason"] for item in sections["discarded"]["items"]})
            self.assertTrue(all(item["kind"] in {"task", "workflow_proposal", "audit_event"} for section in sections.values() for item in section["items"]))
            self.assertTrue(any(item["title"] == "workflow_proposal.rejected" and item["reason"] == "Bad fit" for item in sections["audit"]["items"]))

    def test_operations_feed_deduplicates_tasks_and_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Expansion", "value": 25000})
            deal_id = deal_payload["deal"]["id"]
            handle_action(temporary_dir, "crm.create_task", {"title": "Existing deal follow-up", "deal_id": deal_id})

            _, feed = handle_action(temporary_dir, "crm.operations_feed", {"limit": 20})
            to_do = next(section for section in feed["sections"] if section["key"] == "to_do")

            self.assertEqual(feed["counts"]["to_do"], 1)
            self.assertEqual([item["kind"] for item in to_do["items"]], ["task"])
            self.assertEqual(to_do["items"][0]["title"], "Existing deal follow-up")

    def test_operations_feed_filters_owner_and_overdue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            handle_action(temporary_dir, "crm.create_task", {"title": "Owner A overdue", "owner_id": "owner_a", "due_at": "2000-01-01"})
            handle_action(temporary_dir, "crm.create_task", {"title": "Owner A future", "owner_id": "owner_a", "due_at": "2999-01-01"})
            handle_action(temporary_dir, "crm.create_task", {"title": "Owner B overdue", "owner_id": "owner_b", "due_at": "2000-01-01"})

            _, feed = handle_action(temporary_dir, "crm.operations_feed", {"owner_id": "owner_a", "due_overdue": True, "kind": "task", "status": "open", "limit": 20})
            to_do = next(section for section in feed["sections"] if section["key"] == "to_do")

            self.assertEqual(feed["counts"]["to_do"], 1)
            self.assertEqual([item["title"] for item in to_do["items"]], ["Owner A overdue"])

    def test_operations_feed_counts_exceed_limited_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            for index in range(5):
                handle_action(temporary_dir, "crm.create_task", {"title": f"Limited task {index}", "due_at": f"2999-01-0{index + 1}"})

            _, feed = handle_action(temporary_dir, "crm.operations_feed", {"limit": 2, "kind": "task", "status": "open"})
            to_do = next(section for section in feed["sections"] if section["key"] == "to_do")

            self.assertEqual(feed["counts"]["to_do"], 5)
            self.assertEqual(to_do["count"], 5)
            self.assertEqual(len(to_do["items"]), 2)

    def test_archive_delete_and_tag_record_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Tagged Account"})
            account_id = account_payload["account"]["id"]

            _, tagged = handle_action(temporary_dir, "crm.tag_record", {"entity_type": "account", "id": account_id, "tag": "Important", "color": "#2457a6"})
            self.assertEqual(tagged["record"]["tags"][0]["name"], "Important")

            _, untagged = handle_action(temporary_dir, "crm.untag_record", {"entity_type": "account", "id": account_id, "tag": "Important"})
            self.assertEqual(untagged["record"]["tags"], [])

            handle_action(temporary_dir, "crm.archive_record", {"entity_type": "account", "id": account_id})
            _, bootstrap = handle_action(temporary_dir, "bootstrap", {})
            self.assertEqual(bootstrap["accounts"], [])

            handle_action(temporary_dir, "crm.unarchive_record", {"entity_type": "account", "id": account_id})
            _, restored = handle_action(temporary_dir, "bootstrap", {})
            self.assertEqual(restored["accounts"][0]["id"], account_id)

            _, deleted = handle_action(temporary_dir, "crm.delete_record", {"entity_type": "account", "id": account_id})
            self.assertTrue(deleted["ok"])
            _, after_delete = handle_action(temporary_dir, "bootstrap", {})
            self.assertEqual(after_delete["accounts"], [])

    def test_delete_record_rejects_active_dependents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Parent Account"})
            account_id = account_payload["account"]["id"]
            handle_action(temporary_dir, "crm.create_contact", {"display_name": "Linked Contact", "account_id": account_id})

            with self.assertRaisesRegex(ValidationError, "active linked records"):
                handle_action(temporary_dir, "crm.delete_record", {"entity_type": "account", "id": account_id})

    def test_active_records_cannot_link_archived_parents_and_health_reports_violations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Archived Parent"})
            account_id = account_payload["account"]["id"]
            handle_action(temporary_dir, "crm.archive_record", {"entity_type": "account", "id": account_id})

            with self.assertRaisesRegex(ValidationError, "archived"):
                handle_action(temporary_dir, "crm.create_contact", {"display_name": "Bad Link", "account_id": account_id})

            now = utc_now()
            with connect(temporary_dir) as db:
                db.execute(
                    """
                    INSERT INTO contacts(id, account_id, display_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("cont_bad_archived_parent", account_id, "Bad Link", now, now),
                )

            _, health = handle_action(temporary_dir, "crm.health", {})
            self.assertFalse(health["ok"])
            self.assertEqual(health["checks"]["references"]["archived_parent_counts"]["contacts.account_id"], 1)

    def test_health_checks_schema_fts_references_view_state_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Healthy Account"})
            account_id = account_payload["account"]["id"]
            _, healthy = handle_action(temporary_dir, "crm.health", {})
            self.assertTrue(healthy["ok"])
            self.assertTrue(healthy["checks"]["fts"]["ok"])

            with connect(temporary_dir) as db:
                delete_fts(db, "account", account_id)

            _, degraded = handle_action(temporary_dir, "crm.health", {})
            self.assertFalse(degraded["ok"])
            self.assertEqual(degraded["status"], "degraded")
            self.assertEqual(degraded["checks"]["fts"]["missing"]["account"], 1)

    def test_health_reports_custom_field_orphans_and_invalid_workflow_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Workflow Health"})
            account_id = account_payload["account"]["id"]
            now = utc_now()

            with connect(temporary_dir) as db:
                db.execute(
                    """
                    INSERT INTO custom_field_values(entity_type, entity_id, field_id, value_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("account", account_id, "missing_field", '"orphan"', now),
                )
                db.execute(
                    """
                    INSERT INTO workflow_proposals(id, proposal_type, status, entity_type, entity_id, title, proposal_json, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "wf_invalid_action",
                        "enrichment",
                        "approved",
                        "account",
                        account_id,
                        "Invalid action",
                        '{"action":{"type":"update_record","entity_type":"account","id":"acct_missing","changes":{}}}',
                        "test",
                        now,
                        now,
                    ),
                )

            _, health = handle_action(temporary_dir, "crm.health", {})
            self.assertFalse(health["ok"])
            self.assertEqual(health["checks"]["custom_field_values"]["missing_field_definition"], 1)
            self.assertEqual(health["checks"]["workflow_proposals"]["invalid_count"], 1)

    def test_validation_errors_are_predictable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaises(ValidationError):
                handle_action(temporary_dir, "crm.create_deal", {"name": "Bad stage", "stage_id": "missing"})

            payload = {"id": "acct_duplicate", "name": "Acme"}
            handle_action(temporary_dir, "crm.create_account", payload)
            with self.assertRaises(ValidationError):
                handle_action(temporary_dir, "crm.create_account", payload)

            with self.assertRaisesRegex(ValidationError, "`value` must be a number"):
                handle_action(temporary_dir, "crm.create_deal", {"name": "Bad value", "value": "not-a-number"})

    def test_alias_write_actions_emit_app_events(self) -> None:
        self.assertEqual(app_events_for_action("create_task")[0]["resource"], "records")
        self.assertEqual(app_events_for_action("import_commit")[0]["resource"], "records")
        self.assertEqual(app_events_for_action("set_view_filter")[0]["resource"], "view-state")

    def test_operations_manifest_lists_published_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, manifest = handle_action(temporary_dir, "operations.manifest", {})
            self.assertIn("crm.export", manifest["actions"])
            self.assertIn("crm.records_table", manifest["actions"])
            self.assertIn("crm.view_filter", manifest["actions"])
            self.assertIn("crm.set_custom_view", manifest["actions"])
            self.assertIn("crm.clear_custom_view", manifest["actions"])

    def test_records_table_paginates_sorts_filters_and_computes_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Acme", "domain": "acme.example", "owner_id": "owner_1"})
            account_id = account_payload["account"]["id"]
            handle_action(temporary_dir, "crm.create_contact", {"display_name": "Ada Contact", "account_id": account_id})
            handle_action(temporary_dir, "crm.create_task", {"title": "Call Acme", "account_id": account_id, "status": "open", "due_at": "2026-05-22"})
            handle_action(temporary_dir, "crm.log_activity", {"subject": "Discovery", "account_id": account_id, "occurred_at": "2026-05-21T10:00:00+00:00"})
            handle_action(temporary_dir, "crm.create_deal", {"name": "Small deal", "account_id": account_id, "value": 1000, "stage_id": "qualified"})
            handle_action(temporary_dir, "crm.create_deal", {"name": "Large deal", "account_id": account_id, "value": 9000, "stage_id": "proposal"})
            for index in range(2):
                handle_action(
                    temporary_dir,
                    "crm.link_external_ref",
                    {
                        "crm_entity_type": "account",
                        "crm_entity_id": account_id,
                        "source_app_id": "mail",
                        "source_entity_type": "thread",
                        "source_entity_id": f"thread_{index}",
                        "link_type": "email_thread",
                        "title": f"Account thread {index}",
                    },
                )
            handle_action(
                temporary_dir,
                "crm.link_external_ref",
                {
                    "crm_entity_type": "account",
                    "crm_entity_id": account_id,
                    "source_app_id": "calendar",
                    "source_entity_type": "event",
                    "source_entity_id": "event_1",
                    "link_type": "sales_call",
                    "title": "Discovery call",
                    "occurred_at": "2999-05-30T10:00:00+00:00",
                },
            )
            handle_action(
                temporary_dir,
                "crm.link_external_ref",
                {
                    "crm_entity_type": "account",
                    "crm_entity_id": account_id,
                    "source_app_id": "storage",
                    "source_entity_type": "file",
                    "source_entity_id": "file_brief",
                    "link_type": "brief",
                    "title": "Account brief",
                },
            )
            handle_action(
                temporary_dir,
                "crm.create_automation_rule",
                {
                    "name": "Approve account follow-up",
                    "trigger_event": "account.connections",
                    "entity_type": "account",
                    "conditions": {},
                    "action": {"type": "create_task", "title": "Review account context"},
                },
            )
            handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "account.connections", "entity_type": "account", "entity_id": account_id})

            _, first_page = handle_action(
                temporary_dir,
                "crm.records_table",
                {
                    "entity_type": "deal",
                    "sort": {"field": "value", "direction": "desc"},
                    "pagination": {"limit": 1},
                },
            )
            self.assertEqual(first_page["records"][0]["title"], "Large deal")
            self.assertTrue(first_page["has_more"])
            cursor = json.loads(first_page["next_cursor"])
            self.assertEqual(cursor["sort_field"], "value")
            self.assertEqual(cursor["direction"], "desc")
            self.assertEqual(cursor["entity_type"], "deal")
            self.assertEqual(cursor["order_number"], 9000.0)
            self.assertEqual(first_page["columns"][0]["key"], "name")

            _, second_page = handle_action(
                temporary_dir,
                "crm.records_table",
                {
                    "entity_type": "deal",
                    "sort": {"field": "value", "direction": "desc"},
                    "pagination": {"limit": 1, "cursor": first_page["next_cursor"]},
                },
            )
            self.assertEqual(second_page["records"][0]["title"], "Small deal")

            _, accounts = handle_action(
                temporary_dir,
                "crm.records_table",
                {
                    "entity_type": "account",
                    "filters": {"owner_id": "owner_1"},
                    "pagination": {"limit": 10},
                },
            )
            self.assertEqual(accounts["counts"]["account"], 1)
            self.assertEqual(accounts["records"][0]["computed"]["open_task_count"], 1)
            self.assertEqual(accounts["records"][0]["computed"]["contact_count"], 1)
            self.assertEqual(accounts["records"][0]["computed"]["open_deal_value"], 10000.0)
            self.assertEqual(accounts["records"][0]["computed"]["next_action"], "Call Acme")
            self.assertEqual(accounts["records"][0]["computed"]["last_activity_at"], "2026-05-21T10:00:00+00:00")
            self.assertIn("connections", [column["key"] for column in accounts["columns"]])
            connection_summary = accounts["records"][0]["computed"]["connection_summary"]
            self.assertEqual(connection_summary["mail_count"], 2)
            self.assertEqual(connection_summary["calendar_count"], 1)
            self.assertEqual(connection_summary["file_count"], 1)
            self.assertEqual(connection_summary["approval_count"], 1)
            self.assertIn("Mail 2", [badge["label"] for badge in connection_summary["badges"]])

    def test_pipeline_board_attaches_deal_connection_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Connected Account"})
            account_id = account_payload["account"]["id"]
            _, deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Connected Deal", "account_id": account_id, "value": 25000, "stage_id": "qualified"})
            deal_id = deal_payload["deal"]["id"]
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "account", "crm_entity_id": account_id, "source_app_id": "mail", "source_entity_type": "thread", "source_entity_id": "thread_account"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "deal", "crm_entity_id": deal_id, "source_app_id": "calendar", "source_entity_type": "event", "source_entity_id": "event_deal", "occurred_at": "2999-05-30T10:00:00+00:00"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "deal", "crm_entity_id": deal_id, "source_app_id": "storage", "source_entity_type": "file", "source_entity_id": "brief_deal", "link_type": "brief"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "deal", "crm_entity_id": deal_id, "source_app_id": "agents", "source_entity_type": "run", "source_entity_id": "agent_run_deal", "link_type": "agent_activity"})
            handle_action(
                temporary_dir,
                "crm.create_automation_rule",
                {
                    "name": "Review inherited context",
                    "trigger_event": "deal.connections",
                    "entity_type": "account",
                    "conditions": {},
                    "action": {"type": "create_task", "title": "Approve inherited context"},
                },
            )
            handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "deal.connections", "entity_type": "account", "entity_id": account_id})
            _, stale_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Stale Deal", "value": 5000, "stage_id": "qualified"})
            stale_deal_id = stale_payload["deal"]["id"]
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "deal", "crm_entity_id": stale_deal_id, "source_app_id": "mail", "source_entity_type": "thread", "source_entity_id": "thread_stale", "occurred_at": "2000-01-01T00:00:00+00:00"})

            _, board = handle_action(temporary_dir, "crm.pipeline_board", {})
            connected = next(deal for stage in board["stages"] for deal in stage["deals"] if deal["id"] == deal_id)
            stale = next(deal for stage in board["stages"] for deal in stage["deals"] if deal["id"] == stale_deal_id)

            self.assertEqual(connected["connection_summary"]["mail_count"], 1)
            self.assertEqual(connected["connection_summary"]["calendar_count"], 1)
            self.assertTrue(connected["connection_summary"]["brief_ready"])
            self.assertTrue(connected["connection_summary"]["has_recent_touch"])
            self.assertFalse(stale["connection_summary"]["has_recent_touch"])

            _, detail_refs = handle_action(temporary_dir, "crm.external_timeline", {"entity_type": "deal", "id": deal_id})
            refs_by_source_id = {item["source_entity_id"]: item for item in detail_refs["items"]}
            self.assertEqual(refs_by_source_id["thread_account"]["relationship_scope"], "inherited")
            self.assertEqual(refs_by_source_id["thread_account"]["origin"]["entity_type"], "account")
            self.assertEqual(refs_by_source_id["thread_account"]["origin"]["title"], "Connected Account")
            self.assertEqual(refs_by_source_id["event_deal"]["relationship_scope"], "direct")
            self.assertEqual(detail_refs["connection_summary"]["approval_count"], 1)
            self.assertEqual(detail_refs["connection_summary"]["agent_count"], 1)

    def test_records_table_pushes_tag_query_custom_fields_and_labels_to_sql(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Tagged Acme", "domain": "acme.example"})
            account_id = account_payload["account"]["id"]
            _, contact_payload = handle_action(temporary_dir, "crm.create_contact", {"display_name": "Ada Buyer", "account_id": account_id})
            handle_action(temporary_dir, "crm.create_account", {"name": "Other Account", "domain": "other.example"})
            handle_action(temporary_dir, "crm.tag_record", {"entity_type": "account", "id": account_id, "tag": "Strategic"})
            handle_action(temporary_dir, "crm.define_custom_field", {"entity_type": "account", "field_key": "tier", "label": "Tier", "field_type": "text"})
            handle_action(temporary_dir, "crm.set_custom_fields", {"entity_type": "account", "id": account_id, "custom_fields": {"tier": "enterprise"}})
            handle_action(temporary_dir, "crm.create_deal", {"name": "Readable deal", "account_id": account_id, "contact_id": contact_payload["contact"]["id"]})

            _, page = handle_action(
                temporary_dir,
                "crm.records_table",
                {
                    "entity_type": "account",
                    "query": "acme",
                    "filters": {"tag": "strategic", "custom_fields": {"tier": "enterprise"}},
                    "pagination": {"limit": 10},
                },
            )
            self.assertEqual([record["id"] for record in page["records"]], [account_id])
            self.assertEqual(page["records"][0]["record"]["custom_fields"]["tier"], "enterprise")
            self.assertIn({"key": "custom:tier", "label": "Tier"}, page["columns"])

            _, deals = handle_action(temporary_dir, "crm.records_table", {"entity_type": "deal", "query": "Readable", "pagination": {"limit": 10}})
            deal_column_keys = [column["key"] for column in deals["columns"]]
            self.assertNotIn("account_id", deal_column_keys)
            self.assertNotIn("contact_id", deal_column_keys)
            self.assertEqual(deals["records"][0]["record"]["account_id"], account_id)
            self.assertEqual(deals["records"][0]["record"]["contact_id"], contact_payload["contact"]["id"])
            self.assertEqual(deals["records"][0]["display"]["account"], "Tagged Acme")
            self.assertEqual(deals["records"][0]["display"]["contact"], "Ada Buyer")

    def test_records_table_hydrates_page_records_in_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            for index in range(8):
                _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": f"Batch Account {index:02d}"})
                if index == 7:
                    handle_action(temporary_dir, "crm.tag_record", {"entity_type": "account", "id": account_payload["account"]["id"], "tag": "Batch"})
                    handle_action(temporary_dir, "crm.define_custom_field", {"entity_type": "account", "field_key": "tier", "label": "Tier", "field_type": "text"})
                    handle_action(temporary_dir, "crm.set_custom_fields", {"entity_type": "account", "id": account_payload["account"]["id"], "custom_fields": {"tier": "enterprise"}})

            statements: list[str] = []
            with connect(temporary_dir) as db:
                db.set_trace_callback(lambda statement: statements.append(" ".join(statement.split()).lower()))
                page = records_table(db, {"entity_type": "account", "query": "Batch Account 07", "pagination": {"limit": 5}})

            self.assertEqual(len(page["records"]), 1)
            self.assertTrue(any(record["record"]["custom_fields"].get("tier") == "enterprise" for record in page["records"]))
            self.assertEqual([statement for statement in statements if "from accounts where id =" in statement], [])
            self.assertEqual(len([statement for statement in statements if "select * from accounts where id in" in statement]), 1)

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

    def test_typed_custom_fields_schema_and_export_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as target_dir:
            _, field = handle_action(source_dir, "crm.define_custom_field", {"entity_type": "account", "field_key": "segment", "label": "Segment", "field_type": "select", "options": ["SMB", "Enterprise"]})
            self.assertEqual(field["custom_field"]["field_type"], "select")

            _, account_payload = handle_action(source_dir, "crm.create_account", {"name": "Custom Account"})
            account_id = account_payload["account"]["id"]
            _, updated = handle_action(source_dir, "crm.set_custom_fields", {"entity_type": "account", "id": account_id, "custom_fields": {"segment": "SMB"}})
            self.assertEqual(updated["record"]["custom_fields"]["segment"], "SMB")

            _, schema = handle_action(source_dir, "crm.schema", {})
            self.assertEqual(schema["custom_fields"][0]["field_key"], "segment")

            _, export_result = handle_action(source_dir, "crm.export", {})
            _, imported = handle_action(target_dir, "crm.import_commit", export_result)
            self.assertGreaterEqual(imported["created_count"], 3)
            _, restored = handle_action(target_dir, "crm.get_record", {"entity_type": "account", "id": account_id})
            self.assertEqual(restored["record"]["custom_fields"]["segment"], "SMB")

    def test_enrichment_intelligent_actions_and_approvable_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Workflow Account", "domain": "workflow.example"})
            account_id = account_payload["account"]["id"]
            _, contact_payload = handle_action(temporary_dir, "crm.create_contact", {"display_name": "Workflow Contact", "email": "person@workflow.example"})
            contact_id = contact_payload["contact"]["id"]
            _, enrichment = handle_action(temporary_dir, "crm.record_enrichment", {"entity_type": "contact", "id": contact_id, "create_proposal": True})
            self.assertTrue(any(item["field"] == "account_id" for item in enrichment["suggestions"]))

            proposal_id = enrichment["workflow_proposal"]["id"]
            handle_action(temporary_dir, "crm.approve_workflow_proposal", {"id": proposal_id})
            _, applied = handle_action(temporary_dir, "crm.apply_workflow_proposal", {"id": proposal_id})
            self.assertEqual(applied["record"]["account_id"], account_id)

            handle_action(temporary_dir, "crm.create_deal", {"name": "Workflow Deal", "account_id": account_id, "value": 25000, "stage_id": "proposal"})
            _, actions = handle_action(temporary_dir, "crm.intelligent_next_actions", {})
            self.assertTrue(any(action["kind"] == "recommendation" and action["entity_type"] == "deal" for action in actions["actions"]))

            _, brief = handle_action(temporary_dir, "crm.account_brief", {"account_id": account_id})
            self.assertEqual(brief["metrics"]["open_deals"], 1)
            self.assertIn("Workflow Account", brief["brief"])

    def test_sales_reports_and_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, lead_payload = handle_action(temporary_dir, "crm.create_lead", {"display_name": "Report Lead", "email": "report@example.com"})
            handle_action(temporary_dir, "crm.convert_lead", {"lead_id": lead_payload["lead"]["id"], "deal_name": "Converted report deal", "value": 1000})
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Report Account", "owner_id": "owner_1"})
            account_id = account_payload["account"]["id"]
            _, deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Report Deal", "account_id": account_id, "value": 20000, "stage_id": "proposal", "owner_id": "owner_1"})
            deal_id = deal_payload["deal"]["id"]
            _, past_deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Past Call Deal", "account_id": account_id, "value": 7000, "stage_id": "qualified", "owner_id": "owner_1"})
            past_deal_id = past_deal_payload["deal"]["id"]
            _, won_deal_payload = handle_action(temporary_dir, "crm.create_deal", {"name": "Closed Call Deal", "account_id": account_id, "value": 90000, "stage_id": "won", "owner_id": "owner_1"})
            won_deal_id = won_deal_payload["deal"]["id"]
            handle_action(temporary_dir, "crm.create_task", {"title": "Overdue report task", "account_id": account_id, "owner_id": "owner_1", "due_at": "2026-01-01T00:00:00+00:00"})
            handle_action(temporary_dir, "crm.create_task", {"title": "Future report task", "account_id": account_id, "owner_id": "owner_1", "due_at": "2999-01-01T00:00:00+00:00"})
            handle_action(temporary_dir, "crm.log_activity", {"subject": "Report call", "account_id": account_id, "owner_id": "owner_1", "activity_type": "call"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "lead", "crm_entity_id": lead_payload["lead"]["id"], "source_app_id": "mail", "source_entity_type": "thread", "source_entity_id": "thread_report"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "deal", "crm_entity_id": deal_id, "source_app_id": "calendar", "source_entity_type": "event", "source_entity_id": "event_report", "occurred_at": "2999-05-30T10:00:00+00:00"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "deal", "crm_entity_id": past_deal_id, "source_app_id": "calendar", "source_entity_type": "event", "source_entity_id": "event_past", "occurred_at": "2000-05-30T10:00:00+00:00"})
            handle_action(temporary_dir, "crm.link_external_ref", {"crm_entity_type": "deal", "crm_entity_id": won_deal_id, "source_app_id": "calendar", "source_entity_type": "event", "source_entity_id": "event_won", "occurred_at": "2999-05-30T10:30:00+00:00"})
            handle_action(temporary_dir, "crm.update_pipeline_stage", {"id": "won", "name": "Closed won", "probability": 1.0})
            handle_action(temporary_dir, "crm.create_automation_rule", {"name": "Pending report approval", "trigger_event": "report.pending", "entity_type": "account", "conditions": {}, "action": {"type": "create_task", "title": "Pending approval task"}})
            handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "report.pending", "entity_type": "account", "entity_id": account_id})
            handle_action(temporary_dir, "crm.create_automation_rule", {"name": "Second pending report approval", "trigger_event": "report.pending.second", "entity_type": "account", "conditions": {}, "action": {"type": "create_task", "title": "Second pending approval task"}})
            handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "report.pending.second", "entity_type": "account", "entity_id": account_id})
            handle_action(temporary_dir, "crm.create_automation_rule", {"name": "Approved report approval", "trigger_event": "report.approved", "entity_type": "account", "conditions": {}, "action": {"type": "create_task", "title": "Approved approval task"}})
            _, approved = handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "report.approved", "entity_type": "account", "entity_id": account_id})
            handle_action(temporary_dir, "crm.approve_workflow_proposal", {"id": approved["workflow_proposals"][0]["id"]})

            _, reports = handle_action(temporary_dir, "crm.sales_reports", {})
            self.assertTrue(any(item["stage_id"] == "proposal" and item["total_value"] == 20000 for item in reports["pipeline_value_by_stage"]))
            self.assertGreater(reports["weighted_forecast"]["total_weighted_value"], 0)
            self.assertEqual(reports["lead_conversion"]["converted"], 1)
            self.assertEqual(reports["task_overdue"]["total"], 1)
            self.assertEqual(reports["task_overdue"]["drilldown_filters"], {"kind": "task", "status": "open", "due_overdue": "true"})
            self.assertEqual(reports["task_overdue"]["by_owner"][0]["drilldown_filters"]["owner_id"], "owner_1")
            self.assertEqual(reports["activities_by_owner"][0]["owner_id"], "owner_1")
            self.assertEqual(reports["activities_by_owner"][0]["drilldown_filters"], {"kind": "activity", "owner_id": "owner_1"})
            self.assertEqual(reports["connection_metrics"]["leads_with_linked_email"], 1)
            self.assertEqual(reports["connection_metrics"]["deals_with_scheduled_call"], 1)
            self.assertEqual(reports["connection_metrics"]["records_with_pending_approvals"], 1)
            self.assertEqual(reports["connection_metrics"]["pipeline_value_with_next_call"], {"EUR": 20000.0})

            _, audit = handle_action(temporary_dir, "crm.audit_log", {"entity_type": "account", "entity_id": account_id, "event_type": "account.created"})
            self.assertEqual(audit["events"][0]["event_type"], "account.created")

    def test_merge_records_preserves_commercial_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, field = handle_action(temporary_dir, "crm.define_custom_field", {"entity_type": "account", "field_key": "segment", "label": "Segment"})
            self.assertEqual(field["custom_field"]["field_key"], "segment")
            _, target_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Merge Target", "domain": "merge.example"})
            _, source_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Merge Source", "industry": "Software", "owner_id": "owner_source"})
            target_id = target_payload["account"]["id"]
            source_id = source_payload["account"]["id"]
            handle_action(temporary_dir, "crm.tag_record", {"entity_type": "account", "id": source_id, "tag": "Priority"})
            handle_action(temporary_dir, "crm.set_custom_fields", {"entity_type": "account", "id": source_id, "custom_fields": {"segment": "Enterprise"}})
            handle_action(temporary_dir, "crm.create_task", {"title": "Source task", "account_id": source_id})
            handle_action(temporary_dir, "crm.create_note", {"body": "Source note", "account_id": source_id})
            handle_action(temporary_dir, "crm.log_activity", {"subject": "Source activity", "account_id": source_id})
            handle_action(
                temporary_dir,
                "crm.link_external_ref",
                {"crm_entity_type": "account", "crm_entity_id": source_id, "source_app_id": "mail", "source_entity_type": "thread", "source_entity_id": "thread_merge"},
            )

            _, merged = handle_action(temporary_dir, "crm.merge_records", {"entity_type": "account", "target_id": target_id, "source_ids": [source_id]})
            self.assertEqual(merged["target"]["industry"], "Software")
            self.assertEqual(merged["target"]["custom_fields"]["segment"], "Enterprise")
            self.assertEqual(merged["target"]["tags"][0]["name"], "Priority")
            _, tasks = handle_action(temporary_dir, "crm.filter_records", {"entity_type": "task", "filters": {"account_id": target_id}})
            self.assertEqual(tasks["records"][0]["account_id"], target_id)
            _, refs = handle_action(temporary_dir, "crm.list_external_refs", {"crm_entity_type": "account", "crm_entity_id": target_id})
            self.assertEqual(refs["external_refs"][0]["source_entity_id"], "thread_merge")
            _, audit = handle_action(temporary_dir, "crm.audit_log", {"entity_type": "account", "entity_id": target_id, "event_type": "record.merged"})
            self.assertEqual(audit["events"][0]["payload"]["source_ids"], [source_id])
            with self.assertRaises(NotFoundError):
                handle_action(temporary_dir, "crm.get_record", {"entity_type": "account", "id": source_id})

    def test_automation_rules_create_deduped_approval_proposals_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Automation Account", "status": "prospect"})
            account_id = account_payload["account"]["id"]
            handle_action(
                temporary_dir,
                "crm.create_automation_rule",
                {
                    "name": "Prospect follow-up",
                    "trigger_event": "account.created",
                    "entity_type": "account",
                    "conditions": {"status": "prospect"},
                    "action": {"type": "create_task", "title": "Call prospect", "priority": "high"},
                    "approval_required": False,
                },
            )
            _, first = handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "account.created", "entity_type": "account", "entity_id": account_id})
            self.assertEqual(first["created_count"], 1)
            self.assertEqual(first["workflow_proposals"][0]["status"], "pending")
            _, second = handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "account.created", "entity_type": "account", "entity_id": account_id})
            self.assertEqual(second["created_count"], 0)
            self.assertEqual(second["skipped_duplicate_count"], 1)
            _, tasks_before = handle_action(temporary_dir, "crm.filter_records", {"entity_type": "task"})
            self.assertEqual(tasks_before["records"], [])

            proposal_id = first["workflow_proposals"][0]["id"]
            handle_action(temporary_dir, "crm.approve_workflow_proposal", {"id": proposal_id})
            _, applied = handle_action(temporary_dir, "crm.apply_workflow_proposal", {"id": proposal_id})
            self.assertEqual(applied["record"]["account_id"], account_id)

    def test_workflow_proposals_can_be_dismissed_or_rejected_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Lifecycle Account"})
            account_id = account_payload["account"]["id"]
            handle_action(
                temporary_dir,
                "crm.create_automation_rule",
                {
                    "name": "Lifecycle follow-up",
                    "trigger_event": "account.created",
                    "entity_type": "account",
                    "conditions": {},
                    "action": {"type": "create_task", "title": "Review lifecycle"},
                },
            )

            _, first = handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "account.created", "entity_type": "account", "entity_id": account_id})
            dismissed_id = first["workflow_proposals"][0]["id"]
            _, dismissed = handle_action(temporary_dir, "crm.dismiss_workflow_proposal", {"id": dismissed_id, "reason": "Not needed"})
            self.assertEqual(dismissed["workflow_proposal"]["status"], "dismissed")

            with self.assertRaisesRegex(ValidationError, "approved before applying"):
                handle_action(temporary_dir, "crm.apply_workflow_proposal", {"id": dismissed_id})
            with self.assertRaisesRegex(ValidationError, "pending or approved"):
                handle_action(temporary_dir, "crm.approve_workflow_proposal", {"id": dismissed_id})

            _, second = handle_action(temporary_dir, "crm.run_automation_rules", {"trigger_event": "account.created", "entity_type": "account", "entity_id": account_id})
            rejected_id = second["workflow_proposals"][0]["id"]
            handle_action(temporary_dir, "crm.approve_workflow_proposal", {"id": rejected_id})
            _, rejected = handle_action(temporary_dir, "crm.reject_workflow_proposal", {"id": rejected_id})
            self.assertEqual(rejected["workflow_proposal"]["status"], "rejected")

            _, active = handle_action(temporary_dir, "crm.list_workflow_proposals", {"status": "active"})
            self.assertEqual(active["workflow_proposals"], [])
            _, closed = handle_action(temporary_dir, "crm.list_workflow_proposals", {"status": "all"})
            self.assertEqual({item["status"] for item in closed["workflow_proposals"]}, {"dismissed", "rejected"})

    def test_workflow_proposal_preview_shows_update_record_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Preview Account", "status": "prospect", "summary": "Old summary"})
            account_id = account_payload["account"]["id"]
            handle_action(
                temporary_dir,
                "crm.import_commit",
                {
                    "export": {
                        "workflow_proposals": [
                            {
                                "id": "wf_preview_update",
                                "proposal_type": "enrichment",
                                "status": "approved",
                                "entity_type": "account",
                                "entity_id": account_id,
                                "title": "Preview account update",
                                "proposal": {
                                    "reason": "Account qualified",
                                    "action": {
                                        "type": "update_record",
                                        "entity_type": "account",
                                        "id": account_id,
                                        "changes": {"status": "customer", "summary": "New summary"},
                                    },
                                },
                            }
                        ]
                    }
                },
            )

            _, payload = handle_action(temporary_dir, "crm.workflow_proposal_preview", {"id": "wf_preview_update"})

            preview = payload["preview"]
            changes = {item["field"]: item for item in preview["changes"]}
            self.assertEqual(preview["action_type"], "update_record")
            self.assertEqual(preview["target"], {"entity_type": "account", "id": account_id})
            self.assertEqual(changes["status"]["current_value"], "prospect")
            self.assertEqual(changes["status"]["proposed_value"], "customer")
            self.assertEqual(changes["summary"]["current_value"], "Old summary")
            self.assertEqual(changes["summary"]["proposed_value"], "New summary")
            self.assertEqual(preview["validation_issues"], [])
            self.assertTrue(preview["can_apply"])

    def test_workflow_proposal_preview_shows_create_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Task Preview Account"})
            account_id = account_payload["account"]["id"]
            handle_action(
                temporary_dir,
                "crm.import_commit",
                {
                    "export": {
                        "workflow_proposals": [
                            {
                                "id": "wf_preview_task",
                                "proposal_type": "next_action",
                                "status": "pending",
                                "entity_type": "account",
                                "entity_id": account_id,
                                "title": "Create task preview",
                                "proposal": {
                                    "reason": "Needs follow up",
                                    "action": {"type": "create_task", "title": "Call buyer", "priority": "high", "account_id": account_id, "due_at": "2026-06-01"},
                                },
                            }
                        ]
                    }
                },
            )

            _, payload = handle_action(temporary_dir, "crm.workflow_proposal_preview", {"id": "wf_preview_task"})

            preview = payload["preview"]
            self.assertEqual(preview["action_type"], "create_task")
            self.assertEqual(preview["target"], {"entity_type": "account", "id": account_id})
            self.assertEqual(preview["changes"], [])
            self.assertEqual(preview["proposed_task"]["title"], "Call buyer")
            self.assertEqual(preview["proposed_task"]["priority"], "high")
            self.assertEqual(preview["proposed_task"]["account_id"], account_id)
            self.assertEqual(preview["validation_issues"], [])
            self.assertTrue(preview["can_approve"])

    def test_workflow_proposal_preview_returns_validation_issues_for_invalid_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Invalid Preview Account"})
            account_id = account_payload["account"]["id"]
            handle_action(
                temporary_dir,
                "crm.import_commit",
                {
                    "export": {
                        "workflow_proposals": [
                            {
                                "id": "wf_preview_invalid",
                                "proposal_type": "enrichment",
                                "status": "approved",
                                "entity_type": "account",
                                "entity_id": account_id,
                                "title": "Invalid update preview",
                                "proposal": {"action": {"type": "update_record", "entity_type": "account", "id": "missing_account", "changes": {}}},
                            }
                        ]
                    }
                },
            )

            _, payload = handle_action(temporary_dir, "crm.workflow_proposal_preview", {"id": "wf_preview_invalid"})

            preview = payload["preview"]
            self.assertEqual(preview["target"], {"entity_type": "account", "id": "missing_account"})
            self.assertIn("update_record target is not active", preview["validation_issues"])
            self.assertIn("update_record has no applicable changes", preview["validation_issues"])
            self.assertFalse(preview["can_apply"])

    def test_enrichment_does_not_create_noop_workflow_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, contact_payload = handle_action(temporary_dir, "crm.create_contact", {"display_name": "Standalone Contact", "email": "standalone@example.com"})
            _, enrichment = handle_action(temporary_dir, "crm.record_enrichment", {"entity_type": "contact", "id": contact_payload["contact"]["id"], "create_proposal": True})
            self.assertNotIn("workflow_proposal", enrichment)
            self.assertFalse(any(item["field"] == "domain" for item in enrichment["suggestions"]))

            handle_action(temporary_dir, "crm.define_custom_field", {"entity_type": "account", "field_key": "segment", "label": "Segment", "field_type": "text", "required": True})
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "No Default Field"})
            _, required_field_enrichment = handle_action(temporary_dir, "crm.record_enrichment", {"entity_type": "account", "id": account_payload["account"]["id"], "create_proposal": True})
            self.assertNotIn("workflow_proposal", required_field_enrichment)

    def test_empty_update_workflow_proposal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            _, account_payload = handle_action(temporary_dir, "crm.create_account", {"name": "Workflow Guard"})
            account_id = account_payload["account"]["id"]
            import_payload = {
                "export": {
                    "workflow_proposals": [
                        {
                            "id": "wf_empty_update",
                            "proposal_type": "enrichment",
                            "status": "approved",
                            "entity_type": "account",
                            "entity_id": account_id,
                            "title": "Empty update",
                            "proposal": {"action": {"type": "update_record", "entity_type": "account", "id": account_id, "changes": {}}},
                        }
                    ]
                }
            }
            handle_action(temporary_dir, "crm.import_commit", import_payload)

            with self.assertRaisesRegex(ValidationError, "no applicable changes"):
                handle_action(temporary_dir, "crm.apply_workflow_proposal", {"id": "wf_empty_update"})


if __name__ == "__main__":
    unittest.main()
