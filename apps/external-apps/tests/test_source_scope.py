"""Per-app settings narrow existing authority; they never select an exporter."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from support import apply_args, prepare, service
from external_apps.errors import AppError
from external_apps.service import Service
from external_apps.surfaces import validate


class SourceScopeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.service = service(Path(temp.name))
        self.plan = prepare(self.service)
        self.other = Service(self.service.root, replace(self.service.ctx, provider_id="other-exporter"))
        self.other_plan = prepare(self.other)

    def test_catalog_is_filtered_before_pagination_and_get_is_scoped(self):
        for source, plan in (("selected-exporter", self.plan), ("other-exporter", self.other_plan)):
            result = self.service.handle({"action": "list", "source_app_id": source, "limit": 1})
            self.assertEqual(result["total"], 1)
            self.assertEqual([app["id"] for app in result["items"]], [plan["app_id"]])
            self.assertIsNone(result["next_offset"])
            detail = self.service.handle({"action": "get", "source_app_id": source, "external_app_id": plan["app_id"]})
            self.assertEqual(detail["app"]["provider_id"], source)
        self.assertEqual(self.service.handle({"action": "list", "source_app_id": "chat"})["items"], [])
        self.assertEqual(self.service.handle({"action": "list"})["total"], 2)

    def test_cross_source_reads_and_mutations_fail_closed(self):
        for action in ("get", "rollback.plan", "suspend", "archive", "publish.plan"):
            with self.subTest(action=action), self.assertRaises(AppError) as error:
                self.service.handle({"action": action, "external_app_id": self.other_plan["app_id"], "source_app_id": "selected-exporter"})
            self.assertEqual(error.exception.status, 404)
        for action in ("get", "plan.approve", "publish.apply", "rollback.apply"):
            with self.subTest(action=action), self.assertRaises(AppError) as error:
                self.service.handle({"action": action, "plan_id": self.other_plan["id"], "source_app_id": "selected-exporter"})
            self.assertEqual(error.exception.status, 404)
        self.assertEqual(self.service.store.get("plans", self.other_plan["id"])["status"], "ready")

    def test_source_is_not_provider_or_actor_authority(self):
        with self.assertRaisesRegex(AppError, "source_exporter_not_selected"):
            self.service.handle({"action": "publish.plan", "source_app_id": "other-exporter"})
        self.assertEqual(self.service.handle({"action": "health"})["selected_exporter_app_id"], "selected-exporter")
        member = Service(self.service.root, replace(self.service.ctx, workspace_role="viewer"))
        with self.assertRaises(AppError) as error:
            member.handle({"action": "suspend", "external_app_id": self.plan["app_id"], "source_app_id": "selected-exporter"})
        self.assertEqual(error.exception.status, 403)
        agent = Service(self.service.root, replace(self.service.ctx, runtime_session_id="agent"))
        with self.assertRaisesRegex(AppError, "human_ui"):
            agent.handle({"action": "plan.approve", "plan_id": self.plan["id"], "plan_digest": self.plan["plan_digest"], "confirm": True, "source_app_id": "selected-exporter"})

    def test_scoped_approval_apply_and_suspend_reuse_publication_protocol(self):
        scope = {"source_app_id": "selected-exporter"}
        approved = self.service.handle({"action": "plan.approve", "plan_id": self.plan["id"], "plan_digest": self.plan["plan_digest"], "confirm": True, **scope})["plan"]
        result = self.service.handle({**apply_args(approved), **scope})
        self.assertEqual(result["status"], "published")
        result = self.service.handle({"action": "suspend", "external_app_id": self.plan["app_id"], "expected_generation": result["generation"], "confirm": True, "idempotency_key": "scoped-suspend", **scope})
        self.assertEqual(result["status"], "suspended")

    def test_closed_surface_validation(self):
        for source in ("", "   ", None, 42):
            with self.subTest(source=source), self.assertRaises(AppError):
                validate({"action": "list", "source_app_id": source})
        with self.assertRaises(AppError):
            validate({"action": "deployment.configure", "source_app_id": "chat"})
        self.assertEqual(validate({"action": "list", "source_app_id": "chat"})["source_app_id"], "chat")
