"""Contract and product behavior tests for Marta Ops."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from core.apps.contracts import parse_app_contract_file


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT / "backend"))

from errors import MartaOpsError
from service import handle_action


class MartaOpsContractTest(unittest.TestCase):
    def test_contract_parses(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        self.assertEqual(parsed.app_id, "marta-ops")
        self.assertEqual(parsed.contract.distribution.mode, "source_available")
        self.assertEqual(parsed.contract.distribution.source_access, "forkable")
        requirements = {item.alias: item for item in parsed.contract.requires}
        self.assertEqual(requirements["mail"].interface, "mail.workspace")
        self.assertEqual(requirements["calendar"].interface, "calendar.events")
        self.assertEqual(requirements["storage"].interface, "file.catalog")

    def test_sidebar_widgets_are_declared(self) -> None:
        parsed = parse_app_contract_file(APP_ROOT)
        widgets = {widget.widget_id: widget for widget in parsed.contract.widgets}
        self.assertEqual(set(widgets), {"marta-ops-sidebar", "marta-ops-sidebar-footer"})
        self.assertEqual(widgets["marta-ops-sidebar"].content_kinds, ["shell.sidebar.primary"])
        self.assertEqual(widgets["marta-ops-sidebar-footer"].content_kinds, ["shell.sidebar.footer"])
        for widget in widgets.values():
            self.assertTrue((APP_ROOT / widget.frontend.mount).is_dir())


class MartaOpsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def callback(
        self,
        action: str,
        payload: dict,
        *,
        provider: str,
        request: dict | None = None,
        **callback_payload,
    ) -> dict:
        alias = (
            "mail"
            if ".mail_" in action
            else "calendar"
            if ".calendar_" in action
            else "storage"
        )
        _, result = handle_action(
            self.data_root,
            {
                "action": action,
                "_app_surface": "dependency_backend_request_callback",
                "dependency_backend_status": "completed",
                "dependency_alias": alias,
                "dependency_backend_result": {
                    "status_code": 200,
                    "dependency_provider_app_id": provider,
                    "json": payload,
                },
                "request": request or {"body": {}},
                **callback_payload,
            },
        )
        return result

    def configure_mail(self) -> None:
        self.callback(
            "integrations.mail_connections_refreshed",
            {
                "items": [
                    {
                        "id": "mail-1",
                        "display_name": "Marta",
                        "email_address": "marta@example.test",
                        "provider": "gmail",
                        "status": "connected",
                    }
                ]
            },
            provider="mail",
        )

    def configure_calendar(self) -> None:
        self.callback(
            "integrations.calendar_connections_refreshed",
            {
                "connections": [
                    {
                        "id": "cal-1",
                        "account_label": "Marta",
                        "status": "connected",
                    }
                ]
            },
            provider="calendar",
        )
        self.callback(
            "integrations.calendar_calendars_refreshed",
            {
                "calendars": [
                    {
                        "connection_id": "cal-1",
                        "provider_calendar_id": "primary",
                        "summary": "Marta",
                        "timezone": "Europe/Rome",
                        "access_role": "owner",
                        "primary": True,
                        "selected": True,
                    }
                ]
            },
            provider="calendar",
        )

    def test_collaboration_and_deliverable_round_trip(self) -> None:
        _, created = handle_action(
            self.data_root,
            {
                "action": "create_collaboration",
                "collaboration": {
                    "title": "Campagna outdoor",
                    "partner": "Brand",
                    "next_action": "Confermare il brief",
                    "due_date": "2026-10-01",
                    "value_minor": 250000,
                },
            },
        )
        work_id = created["collaboration"]["id"]
        _, changed = handle_action(
            self.data_root,
            {
                "action": "add_deliverable",
                "collaboration_id": work_id,
                "deliverable": {"title": "Reel principale", "due_date": "2026-10-03"},
            },
        )
        deliverable_id = changed["deliverable"]["id"]
        _, updated = handle_action(
            self.data_root,
            {
                "action": "update_deliverable",
                "collaboration_id": work_id,
                "id": deliverable_id,
                "changes": {"status": "published"},
            },
        )

        self.assertEqual(updated["deliverable"]["status"], "published")
        _, bootstrapped = handle_action(self.data_root, {"action": "bootstrap"})
        self.assertEqual(bootstrapped["state"]["collaborations"][0]["value_minor"], 250000)

    def test_partial_update_preserves_existing_fields(self) -> None:
        _, created = handle_action(
            self.data_root,
            {
                "action": "create_collaboration",
                "collaboration": {"title": "Evento", "partner": "Partner", "phase": "confirmed"},
            },
        )
        _, updated = handle_action(
            self.data_root,
            {
                "action": "update_collaboration",
                "id": created["collaboration"]["id"],
                "changes": {"next_action": "Prenotare il viaggio"},
            },
        )
        self.assertEqual(updated["collaboration"]["partner"], "Partner")
        self.assertEqual(updated["collaboration"]["phase"], "confirmed")

    def test_idea_capture_and_status_update(self) -> None:
        _, created = handle_action(
            self.data_root,
            {"action": "create_idea", "idea": {"title": "Una discesa, tre errori", "pillar": "Sci"}},
        )
        _, updated = handle_action(
            self.data_root,
            {"action": "update_idea", "id": created["idea"]["id"], "changes": {"status": "selected"}},
        )
        self.assertEqual(updated["idea"]["status"], "selected")

    def test_invalid_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(MartaOpsError, "data valida"):
            handle_action(
                self.data_root,
                {"action": "create_collaboration", "collaboration": {"title": "Test", "due_date": "domani"}},
            )

    def test_mail_integration_creates_only_a_draft_request(self) -> None:
        self.configure_mail()
        _, created = handle_action(
            self.data_root,
            {
                "action": "create_collaboration",
                "collaboration": {
                    "title": "Campagna neve",
                    "partner": "Brand",
                    "partner_email": "team@example.test",
                    "next_action": "Confermiamo il brief e le date.",
                },
            },
        )
        _, integrated = handle_action(
            self.data_root,
            {"action": "create_mail_draft", "id": created["collaboration"]["id"]},
        )
        request = integrated["dependency_backend_requests"][0]
        self.assertEqual(request["dependency_alias"], "mail")
        self.assertEqual(request["body"]["action"], "mail_create_draft")
        self.assertEqual(request["body"]["connection_id"], "mail-1")
        self.assertEqual(request["body"]["to"], [{"email": "team@example.test"}])
        self.assertEqual(request["body"]["workspace_attachments"], [])
        self.assertNotIn("confirm", request["body"])
        self.assertNotIn("send", request["body"]["action"])

        completed = self.callback(
            "integrations.mail_draft_completed",
            {
                "draft": {
                    "id": "draft-1",
                    "connection_id": "mail-1",
                    "updated_at": "2026-10-01T09:00:00Z",
                }
            },
            provider="mail",
            request=request,
            work_id=created["collaboration"]["id"],
        )
        self.assertEqual(completed["mail_draft"]["id"], "draft-1")
        _, reintegrated = handle_action(
            self.data_root,
            {"action": "create_mail_draft", "id": created["collaboration"]["id"]},
        )
        update = reintegrated["dependency_backend_requests"][0]["body"]
        self.assertEqual(update["action"], "mail_update_draft")
        self.assertEqual(update["draft_id"], "draft-1")
        self.assertNotIn("connection_id", update)

    def test_calendar_integration_creates_an_idempotent_all_day_event(self) -> None:
        self.configure_calendar()
        _, created = handle_action(
            self.data_root,
            {
                "action": "create_collaboration",
                "collaboration": {"title": "Evento", "due_date": "2026-10-01", "next_action": "Confermare la venue"},
            },
        )
        work_id = created["collaboration"]["id"]
        _, integrated = handle_action(self.data_root, {"action": "create_calendar_event", "id": work_id})
        request = integrated["dependency_backend_requests"][0]
        self.assertEqual(request["dependency_alias"], "calendar")
        self.assertEqual(request["body"]["action"], "create")
        self.assertEqual(request["body"]["startTime"], "2026-10-01")
        self.assertEqual(request["body"]["endTime"], "2026-10-02")
        self.assertTrue(request["body"]["all_day"])
        self.assertEqual(request["body"]["source"], "google_calendar")
        self.assertEqual(
            request["body"]["external_refs"]["provider_calendar_id"],
            "primary",
        )
        self.assertEqual(request["body"]["idempotency_key"], f"marta-ops:{work_id}:calendar")

        completed = self.callback(
            "integrations.calendar_event_completed",
            {
                "event": {
                    "id": "event-1",
                    "revision": 3,
                    "startTime": "2026-10-01",
                    "external_refs": request["body"]["external_refs"],
                }
            },
            provider="calendar",
            request=request,
            work_id=work_id,
        )
        self.assertEqual(completed["calendar_event"]["id"], "event-1")
        _, reintegrated = handle_action(
            self.data_root,
            {"action": "create_calendar_event", "id": work_id},
        )
        update = reintegrated["dependency_backend_requests"][0]["body"]
        self.assertEqual(update["action"], "update")
        self.assertEqual(update["id"], "event-1")
        self.assertEqual(update["expected_revision"], 3)

    def test_storage_file_is_verified_linked_and_attached_to_mail(self) -> None:
        self.configure_mail()
        _, created = handle_action(
            self.data_root,
            {
                "action": "create_collaboration",
                "collaboration": {
                    "title": "Campagna",
                    "partner_email": "team@example.test",
                },
            },
        )
        work_id = created["collaboration"]["id"]
        _, link = handle_action(
            self.data_root,
            {
                "action": "link_storage_file",
                "id": work_id,
                "workspace_relative_path": "storage/uploaded/brief.pdf",
            },
        )
        request = link["dependency_backend_requests"][0]
        self.assertEqual(request["body"]["action"], "file_info")
        completed = self.callback(
            "integrations.storage_file_completed",
            {
                "file": {
                    "id": "file-1",
                    "name": "brief.pdf",
                    "workspace_relative_path": "storage/uploaded/brief.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 2048,
                    "sha256": "abc",
                }
            },
            provider="storage",
            request=request,
            work_id=work_id,
        )
        self.assertEqual(completed["document"]["name"], "brief.pdf")
        _, mail = handle_action(
            self.data_root,
            {"action": "create_mail_draft", "id": work_id},
        )
        self.assertEqual(
            mail["dependency_backend_requests"][0]["body"]["workspace_attachments"],
            ["storage/uploaded/brief.pdf"],
        )
        _, unlinked = handle_action(
            self.data_root,
            {"action": "unlink_storage_file", "id": work_id, "document_id": "file-1"},
        )
        self.assertEqual(unlinked["collaboration"]["documents"], [])

    def test_refresh_requests_all_declared_integrations(self) -> None:
        _, refreshed = handle_action(self.data_root, {"action": "refresh_integrations"})
        requests = refreshed["dependency_backend_requests"]
        self.assertEqual(
            [request["dependency_alias"] for request in requests],
            ["mail", "calendar", "calendar", "storage"],
        )
        self.assertTrue(all(request.get("callback") for request in requests))

    def test_integrations_require_their_minimum_fields(self) -> None:
        _, created = handle_action(
            self.data_root,
            {"action": "create_collaboration", "collaboration": {"title": "Senza contatti"}},
        )
        work_id = created["collaboration"]["id"]
        with self.assertRaisesRegex(MartaOpsError, "email del partner"):
            handle_action(self.data_root, {"action": "create_mail_draft", "id": work_id})
        with self.assertRaisesRegex(MartaOpsError, "scadenza"):
            handle_action(self.data_root, {"action": "create_calendar_event", "id": work_id})


if __name__ == "__main__":
    unittest.main()
