"""Real subprocess coverage for worker isolation, bounds and owner cleanup."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from core.shared.entrypoints import EntrypointInterruptedError, EntrypointShutdownController
from core.shared.json_worker_pool import JsonWorkerPool

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = '''
import os, sys, time
from core.app_sdk.json_worker import serve_json_requests
count = 0
def handle(payload):
    global count
    count += 1
    if payload.get("crash"):
        raise ValueError("secret contents must not appear in host errors")
    if payload.get("wrong_id"):
        print('{"request_id":"wrong","result":{}}', flush=True)
        time.sleep(10)
    if payload.get("started"):
        open(payload["started"], "w").write(str(os.getpid()))
    time.sleep(payload.get("sleep", 0))
    return {"pid": os.getpid(), "count": count, "value": payload.get("value"), "large": "x" * payload.get("large", 0)}
serve_json_requests(handle)
'''


class JsonWorkerPoolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.script = self.root / "worker.py"
        self.script.write_text(SCRIPT)
        self.owner = EntrypointShutdownController()
        self.pool = JsonWorkerPool(self.owner, maximum=2, per_identity=1, idle_seconds=0.2)
        self.owner.register_cleanup(self.pool.close)
        self.addCleanup(self.owner.begin_shutdown)

    def invoke(self, payload=None, identity=("user-a",), controller=None, timeout=3):
        return self.pool.invoke(self.script, cwd=ROOT, identity=identity, payload=payload or {},
            timeout_seconds=timeout, controller=controller or self.owner)

    def await_start(self, marker):
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(marker.exists())
        return int(marker.read_text())

    def test_reuses_only_matching_identity_and_new_payload(self):
        first = self.invoke({"value": "old"})
        second = self.invoke({"value": "new"})
        other = self.invoke(identity=("user-b",))
        self.assertEqual(first["pid"], second["pid"])
        self.assertEqual(second["value"], "new")
        self.assertEqual(second["count"], 2)
        self.assertNotEqual(first["pid"], other["pid"])
        self.assertEqual(other["count"], 1)

    def test_source_signature_change_starts_fresh_worker(self):
        first = self.invoke()
        before = self.script.stat()
        self.script.write_text(SCRIPT.replace('count = 0', 'count = 9'))
        os.utime(self.script, ns=(before.st_atime_ns, before.st_mtime_ns))
        second = self.invoke()
        self.assertNotEqual(first["pid"], second["pid"])
        self.assertEqual(second["count"], 10)

    def test_idle_worker_is_reaped_and_busy_worker_is_preserved(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            marker = self.root / "started"
            task = executor.submit(self.invoke, {"started": str(marker), "sleep": 0.35})
            pid = self.await_start(marker)
            time.sleep(0.25)
            os.kill(pid, 0)
            self.assertEqual(task.result()["pid"], pid)
        deadline = time.monotonic() + 2
        while self.pool._workers and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.pool._workers, [])
        self.assertNotEqual(self.invoke()["pid"], pid)

    def test_crash_and_wrong_response_identity_are_not_retried(self):
        for payload in ({"crash": True}, {"wrong_id": True}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError) as error:
                self.invoke(payload)
            self.assertNotIn("secret contents", str(error.exception))
            self.assertEqual(self.pool._workers, [])
        self.assertEqual(self.invoke()["count"], 1)

    def test_timeout_discards_worker(self):
        with self.assertRaises(TimeoutError):
            self.invoke({"sleep": 10}, timeout=0.1)
        self.assertEqual(self.pool._workers, [])
        self.assertEqual(self.invoke()["count"], 1)

    def test_output_size_is_bounded(self):
        with patch("core.shared.json_worker_pool.MAX_MESSAGE_BYTES", 4096):
            with self.assertRaisesRegex(RuntimeError, "framing limit"):
                self.invoke({"large": 8000})
        self.assertEqual(self.pool._workers, [])

    def test_capacity_wait_can_be_cancelled_without_interrupting_active_request(self):
        waiting = EntrypointShutdownController(parent=self.owner, interruption_reason="client disconnect")
        with ThreadPoolExecutor(max_workers=2) as executor:
            marker = self.root / "started"
            active = executor.submit(self.invoke, {"started": str(marker), "sleep": 0.3})
            pid = self.await_start(marker)
            queued = executor.submit(self.invoke, controller=waiting)
            time.sleep(0.02)
            waiting.begin_shutdown()
            with self.assertRaisesRegex(EntrypointInterruptedError, "client disconnect"):
                queued.result(timeout=0.2)
            self.assertEqual(active.result()["pid"], pid)
            self.assertEqual(self.invoke()["pid"], pid)

    def test_host_shutdown_closes_idle_and_active_workers(self):
        idle = self.invoke(identity=("idle",))
        with ThreadPoolExecutor(max_workers=1) as executor:
            marker = self.root / "started"
            active = executor.submit(self.invoke, {"started": str(marker), "sleep": 10})
            self.await_start(marker)
            self.owner.begin_shutdown()
            with self.assertRaises(EntrypointInterruptedError):
                active.result(timeout=1)
        with self.assertRaises(ProcessLookupError):
            os.kill(idle["pid"], 0)
        self.assertEqual(self.pool._workers, [])
