"""Backend recovery phase isolation regressions."""

from __future__ import annotations

from types import SimpleNamespace
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from core.api import backend_recovery


class BackendRecoveryTestCase(unittest.TestCase):
    def test_runtime_recovery_waits_for_bounded_prewarm_priority(self) -> None:
        release = Event()
        prerequisite = Thread(target=release.wait, name="prewarm-fixture", daemon=True)
        prerequisite.start()
        with patch.object(backend_recovery, "_recover_backend_restart") as recover:
            worker = backend_recovery.start_backend_restart_recovery(
                SimpleNamespace(),
                after_threads=(prerequisite,),
                maximum_defer_seconds=1,
            )
            time.sleep(0.05)
            recover.assert_not_called()
            release.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        recover.assert_called_once()

    def test_orchestration_resume_runs_when_runtime_recovery_fails(self) -> None:
        state = SimpleNamespace()

        with (
            patch.object(
                backend_recovery,
                "recover_interrupted_runtime_turns_after_backend_restart",
                side_effect=RuntimeError("corrupt terminalization"),
            ),
            patch.object(backend_recovery, "resume_recovering_orchestrations", return_value=[]) as resume,
            self.assertLogs(backend_recovery.logger, level="ERROR"),
        ):
            backend_recovery._recover_backend_restart(state)

        resume.assert_called_once_with(state)


if __name__ == "__main__":
    unittest.main()
