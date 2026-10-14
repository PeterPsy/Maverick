from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import lab_runtime_control as runtime
import lab_runtime_worker as worker
from lab_runtime_worker import runtime_status


class BrowserLabRuntimeTests(unittest.TestCase):
    def test_owner_stop_remains_disabled_on_direct_service_launch(self):
        with TemporaryDirectory() as folder, patch.object(runtime, "SERVICE_ROOT", Path(folder)), \
             patch.object(runtime, "control", return_value={"status": "stopping"}), \
             patch.object(worker.subprocess, "Popen") as spawn:
            runtime.configure(True)
            runtime.stop()
            worker.main("/supported/node")
            spawn.assert_not_called()
            self.assertEqual((Path(folder) / "lab-enabled").read_text(), "no")
            self.assertEqual(list(Path(folder).iterdir()), [Path(folder) / "lab-enabled"])

    def test_direct_service_launch_rejects_an_enabled_symlink(self):
        with TemporaryDirectory() as folder, patch.object(runtime, "SERVICE_ROOT", Path(folder)), \
             patch.object(worker.subprocess, "Popen") as spawn:
            target = Path(folder) / "other"
            target.write_text("yes")
            (Path(folder) / "lab-enabled").symlink_to(target)
            worker.main("/supported/node")
            spawn.assert_not_called()

    def test_stale_connected_probe_cannot_hide_a_dead_child(self):
        from types import SimpleNamespace
        children = {"playwright": SimpleNamespace(poll=lambda: 1), "broker": SimpleNamespace(poll=lambda: None)}
        self.assertEqual(runtime_status(children, {"connected": True})["status"], "starting")

    def test_worker_receives_runtime_paths_without_parent_credentials(self):
        with TemporaryDirectory() as folder, patch.object(runtime, "SERVICE_ROOT", Path(folder)), \
             patch.object(runtime, "control", side_effect=[{"status": "stopped"}, {"status": "ready"}]), \
             patch.object(runtime.shutil, "which", return_value="/supported/node"), \
             patch.object(runtime.subprocess, "run"), patch.object(runtime.subprocess, "Popen") as spawn, \
             patch.dict(runtime.os.environ, {"PATH": "/bin", "HOME": folder, "LD_LIBRARY_PATH": "/installation/.toolchains/media/lib", "LOOPINO_RUNTIME_API_TOKEN": "private", "VENDOR_API_KEY": "private"}, clear=True):
            self.assertEqual(runtime.ensure_running(enable=True)["status"], "ready")
            environment = spawn.call_args.kwargs["env"]
            self.assertEqual(environment, {"PATH": "/bin", "HOME": folder, "LD_LIBRARY_PATH": "/installation/.toolchains/media/lib"})

    def test_operator_stop_prevents_recovery_from_reopening_worker(self):
        with TemporaryDirectory() as folder, patch.object(runtime, "SERVICE_ROOT", Path(folder)), \
             patch.object(runtime, "control", return_value={"status": "stopping"}), \
             patch.object(runtime.subprocess, "Popen") as spawn:
            runtime.configure(True)
            runtime.stop()
            self.assertEqual(runtime.ensure_running()["status"], "disabled")
            spawn.assert_not_called()
