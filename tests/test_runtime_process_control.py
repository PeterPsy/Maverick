from __future__ import annotations

import subprocess
import time
import unittest

from core.runtime.process_control import register_runtime_process, terminate_runtime_processes


class RuntimeProcessControlTestCase(unittest.TestCase):
    def test_terminates_registered_runtime_process_group(self) -> None:
        process = subprocess.Popen(
            ["python3", "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            register_runtime_process("session-process-kill", process)

            terminated = terminate_runtime_processes("session-process-kill", timeout_seconds=0.2)

            self.assertEqual(terminated, 1)
            deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
