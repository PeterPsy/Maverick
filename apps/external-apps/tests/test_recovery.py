"""Independent-process writers, authoritative cleanup and host revocation."""
from dataclasses import replace
import multiprocessing
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from support import APP_ROOT, apply_args, approve, context, prepare, service, success_probe
from core.apps.installation import install_store_app
from core.apps.registration import register_app_source_from_contract
from core.apps.service import uninstall_workspace_app
from external_apps.errors import AppError
from external_apps.files import publication_lock
from external_apps.maintenance import cleanup
from external_apps.service import Service
from scripts.external_apps_supervisor import selected_mounts
from tests.support.app_hosting import AppHostingTestBase


def apply_worker(root, plan, gate, queue):
    gate.wait(5)
    try:
        result = Service(Path(root), context(), probe=success_probe, preflight=lambda _host: None).handle(apply_args(plan, plan["id"]))
        queue.put(result["status"])
    except AppError as error:
        queue.put(error.code)


class RecoveryTests(unittest.TestCase):
    def test_two_processes_cannot_publish_stale_generations(self):
        with tempfile.TemporaryDirectory() as directory:
            app = service(Path(directory))
            one = approve(app, prepare(app))
            two = approve(app, prepare(app, app_id=one["app_id"], content="two"))
            ctx = multiprocessing.get_context("spawn")
            gate, queue = ctx.Event(), ctx.Queue()
            workers = [ctx.Process(target=apply_worker, args=(directory, plan, gate, queue)) for plan in (one, two)]
            try:
                for worker in workers:
                    worker.start()
                gate.set()
                results = [queue.get(timeout=15) for _ in workers]
                self.assertCountEqual(results, ["published", "binding_changed"])
                for worker in workers:
                    worker.join(5)
                    self.assertEqual(worker.exitcode, 0)
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate(); worker.join(5)
                queue.close(); queue.join_thread()

    def test_expiring_rollback_keeps_release_and_binding_pins_orphan_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            app = service(Path(directory))
            one = approve(app, prepare(app))
            app.handle(apply_args(one))
            two = approve(app, prepare(app, app_id=one["app_id"], content="two"))
            app.handle(apply_args(two, "second-publication"))
            rollback = app.handle({"action": "rollback.plan", "external_app_id": one["app_id"]})["plan"]
            rollback["expires"] = time.time() - 1
            app.store.put("plans", rollback)
            with publication_lock(app.root):
                cleanup(app.store)
            self.assertEqual(app.store.get("releases", one["release_id"])["id"], one["release_id"])
            # Corrupt/private catalog loss must not let GC destroy public authority.
            artifact = app.root / "public/artifacts" / one["release"]["digest"]
            import os
            os.utime(artifact, (0, 0))
            with app.store.connection() as db:
                db.execute("DELETE FROM releases WHERE id=?", (one["release_id"],))
            with publication_lock(app.root):
                cleanup(app.store)
            self.assertTrue(artifact.is_dir())


class SupervisorTests(AppHostingTestBase):
    def test_live_authority_revocation_and_interrupted_operation_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_repo_root(directory)
            (root / "apps/external-apps").symlink_to(APP_ROOT, target_is_directory=True)
            store = self.make_store()
            source = register_app_source_from_contract(store, source_kind="platform", source_path=str(APP_ROOT))
            binding = install_store_app(store, source_id=source.source_id, workspace_id="tenant-a", start_path=root)
            app = service(Path(binding.data_root))
            plan = approve(app, prepare(app))
            def crash(*args):
                raise SystemExit("interrupted HTTP probe")
            app.probe = crash
            with self.assertRaises(SystemExit):
                app.handle(apply_args(plan))
            workspace = SimpleNamespace(status="active")
            workspaces = SimpleNamespace(get_workspace=lambda workspace_id: workspace)
            def mounts():
                return selected_mounts(store, workspaces, selections=[{"workspace_id": "tenant-a"}], domain="apps.example.test", repository=root)
            self.assertEqual(len(mounts()), 1)
            self.assertEqual(app.handle(apply_args(plan))["error_code"], "verification_interrupted")
            workspace.status = "closed"
            self.assertEqual(mounts(), {})
            workspace.status = "active"
            store.save_workspace_app_binding(replace(binding, status="disabled"))
            self.assertEqual(mounts(), {})
            uninstall_workspace_app(store, workspace_id="tenant-a", app_id="external-apps")
            self.assertEqual(mounts(), {})


if __name__ == "__main__":
    unittest.main()
