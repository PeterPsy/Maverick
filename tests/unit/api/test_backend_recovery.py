"""Backend recovery phase isolation regressions."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.api import backend_recovery


class BackendRecoveryTestCase(unittest.TestCase):
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
