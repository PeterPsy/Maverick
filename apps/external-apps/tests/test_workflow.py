"""Preparation, human confirmation, concurrency, failure and restart semantics."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from support import apply_args, approve, context, prepare, service
from external_apps.errors import AppError
from external_apps.files import publication_lock
from external_apps.operations import recover
from external_apps.service import Service
from external_apps.surfaces import validate


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.service = service(self.root)

    def test_plan_never_publishes_and_confirm_boolean_is_not_approval(self):
        plan = prepare(self.service)
        self.assertEqual(plan["status"], "ready")
        app = self.service.handle({"action": "get", "external_app_id": plan["app_id"]})["app"]
        self.assertEqual(app["status"], "draft")
        with self.assertRaisesRegex(AppError, "human_ui"):
            self.service.handle(apply_args(plan))
        for surface in ("cli", "mcp", "dependency_backend"):
            agent = Service(self.root, context(surface=surface))
            with self.assertRaisesRegex(AppError, "human_ui"):
                approve(agent, plan)
        with self.assertRaises(AppError):
            approve(Service(self.root, context(runtime_session_id="agent-session")), plan)
        with self.assertRaises(AppError):
            validate({"action": "plan.approve"}, backend=False)
        with self.assertRaises(AppError):
            validate({"action": "publish.apply", "_app_actor": {"user_id": "admin"}})

    def test_publish_retry_suspend_and_rollback(self):
        one = approve(self.service, prepare(self.service))
        args = apply_args(one)
        first = self.service.handle(args)
        self.assertEqual(first["status"], "published")
        self.assertEqual(first, self.service.handle(args))
        with self.assertRaisesRegex(AppError, "idempotency_conflict"):
            self.service.handle({**args, "confirm": False})
        two = approve(self.service, prepare(self.service, app_id=one["app_id"], content="two"))
        self.service.handle(apply_args(two, "second-publication"))
        rollback = self.service.handle({"action": "rollback.plan", "external_app_id": one["app_id"]})["plan"]
        approve(self.service, rollback)
        result = self.service.handle(apply_args(rollback, "rollback-idempotent"))
        self.assertEqual(result["release_id"], one["release_id"])
        suspended = self.service.handle({"action": "suspend", "external_app_id": one["app_id"], "expected_generation": result["generation"], "confirm": True, "idempotency_key": "suspend-idempotent"})
        self.assertEqual(suspended["status"], "suspended")
        self.assertEqual(self.service.handle(args), first)  # Retry must not resurrect.
        self.assertEqual(self.service.handle({"action": "get", "external_app_id": one["app_id"]})["app"]["status"], "suspended")

    def test_changed_actor_provider_generation_and_expiry(self):
        plan = approve(self.service, prepare(self.service))
        for ctx in (context(user_id="different"), context(provider_id="different")):
            with self.assertRaises(AppError):
                Service(self.root, ctx).handle(apply_args(plan))
        second = approve(self.service, prepare(self.service, app_id=plan["app_id"], content="two"))
        self.service.handle(apply_args(plan))
        with self.assertRaisesRegex(AppError, "binding_changed"):
            self.service.handle(apply_args(second, "changed-generation"))
        expired = prepare(self.service, app_id=plan["app_id"])
        with patch("external_apps.plans.time.time", return_value=expired["expires"] + 1):
            with self.assertRaisesRegex(AppError, "expired"):
                approve(self.service, expired)

    def test_failed_probe_restores_previous(self):
        one = approve(self.service, prepare(self.service))
        self.service.handle(apply_args(one))
        two = approve(self.service, prepare(self.service, app_id=one["app_id"], content="two"))
        def fail(*args):
            raise AppError("public_verification_failed", 503)
        self.service.probe = fail
        result = self.service.handle(apply_args(two, "failed-second-publish"))
        self.assertEqual(result["status"], "failed")
        app = self.service.handle({"action": "get", "external_app_id": one["app_id"]})["app"]
        self.assertEqual(app["binding"]["current"]["release_id"], one["release_id"])

    def test_suspend_during_probe_wins_over_compensation(self):
        entered, proceed = threading.Event(), threading.Event()
        def probe(*args):
            entered.set()
            if not proceed.wait(5):
                raise AssertionError("test deadline")
            raise AppError("public_verification_failed", 503)
        self.service.probe = probe
        plan = approve(self.service, prepare(self.service))
        results = []
        worker = threading.Thread(target=lambda: results.append(self.service.handle(apply_args(plan))))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            result = self.service.handle({"action": "suspend", "external_app_id": plan["app_id"], "expected_generation": 1, "confirm": True, "idempotency_key": "concurrent-suspend"})
            self.assertEqual(result["generation"], 2)
        finally:
            proceed.set()
            worker.join(6)
        self.assertFalse(worker.is_alive())
        app = self.service.handle({"action": "get", "external_app_id": plan["app_id"]})["app"]
        self.assertFalse(app["binding"]["enabled"])
        self.assertEqual(app["binding"]["generation"], 2)

    def test_crash_after_switch_is_recovered_without_verified_success(self):
        plan = approve(self.service, prepare(self.service))
        def crash(*args):
            raise SystemExit("simulated crash")
        self.service.probe = crash
        with self.assertRaises(SystemExit):
            self.service.handle(apply_args(plan))
        with publication_lock(self.root):
            recover(self.service.store)
        app = self.service.handle({"action": "get", "external_app_id": plan["app_id"]})["app"]
        self.assertFalse(app["binding"]["enabled"])
        result = self.service.handle(apply_args(plan))
        self.assertEqual(result["error_code"], "verification_interrupted")

    def test_crash_before_switch_preserves_binding(self):
        plan = approve(self.service, prepare(self.service))
        with patch("external_apps.operations.write_binding", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                self.service.handle(apply_args(plan))
        with publication_lock(self.root):
            recover(self.service.store)
        self.assertEqual(self.service.handle(apply_args(plan))["error_code"], "operation_interrupted")

    def test_workspace_scope_and_callback_spoofing(self):
        with self.assertRaisesRegex(AppError, "workspace_mismatch"):
            Service(self.root, context("tenant-b"))
        with self.assertRaisesRegex(AppError, "callback_surface"):
            self.service.handle({"action": "export.completed"})
        guest = Service(self.root, context(user_id="guest", workspace_role="viewer"))
        with self.assertRaises(AppError):
            guest.handle({"action": "publish.plan"})


if __name__ == "__main__":
    unittest.main()
