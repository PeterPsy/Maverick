from __future__ import annotations

from pathlib import Path
import queue
import tempfile
from threading import Thread
import time
import unittest

from core.shared.entrypoints import EntrypointShutdownController, run_json_entrypoint


REPO_ROOT = Path(__file__).resolve().parents[1]


class SharedEntrypointTests(unittest.TestCase):
    def test_shutdown_controller_interrupts_live_entrypoint_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            entrypoint = temp_root / "slow_entrypoint.py"
            entrypoint.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import sys",
                        "import time",
                        "",
                        "json.loads(sys.stdin.read() or '{}')",
                        "time.sleep(30)",
                        "print('{\"status\": \"ok\"}')",
                    ]
                ),
                encoding="utf-8",
            )
            controller = EntrypointShutdownController()
            failures: queue.Queue[BaseException] = queue.Queue()

            def target() -> None:
                try:
                    run_json_entrypoint(
                        entrypoint,
                        payload={"action": "sleep"},
                        cwd=REPO_ROOT,
                        timeout_seconds=30,
                        shutdown_controller=controller,
                    )
                except BaseException as error:
                    failures.put(error)

            worker = Thread(target=target)
            worker.start()

            deadline = time.time() + 5
            while controller.active_process_count() == 0 and time.time() < deadline:
                time.sleep(0.05)

            self.assertGreater(controller.active_process_count(), 0)

            controller.begin_shutdown()
            worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            error = failures.get_nowait()
            self.assertIsInstance(error, RuntimeError)
            self.assertIn("host shutdown", str(error))


if __name__ == "__main__":
    unittest.main()
