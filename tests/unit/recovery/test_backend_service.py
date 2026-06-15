from __future__ import annotations

import os
import signal
import unittest
from unittest.mock import Mock

from core.recovery.backend_service import restart_backend_service


RUNNING_STATUS = "MainPID=100\nRestart=always\nActiveState=active\nSubState=running\n"
RESTARTED_STATUS = "MainPID=101\nRestart=always\nActiveState=active\nSubState=running\n"
ACCESS_DENIED_RESTART_ERROR = (
    "Failed to restart maverick-core.service: Access denied\n"
    "See system logs and 'systemctl status maverick-core.service' for details."
)


class CompletedProcessStub:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class HealthResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class RecoveryBackendServiceTest(unittest.TestCase):
    def test_restart_backend_service_falls_back_to_signalling_main_pid(self) -> None:
        restart_errors = (
            "Interactive authentication required.\n",
            ACCESS_DENIED_RESTART_ERROR,
        )

        for restart_error in restart_errors:
            with self.subTest(restart_error=restart_error):
                responses = [
                    CompletedProcessStub(returncode=0, stdout=RUNNING_STATUS),
                    CompletedProcessStub(returncode=1, stderr=restart_error),
                    CompletedProcessStub(returncode=0, stdout=RESTARTED_STATUS),
                ]

                def fake_runner(*args, **kwargs):
                    return responses.pop(0)

                killer = Mock()

                with unittest.mock.patch("core.recovery.backend_service.urlopen", return_value=HealthResponse(200)):
                    result = restart_backend_service(
                        process_runner=fake_runner,
                        process_killer=killer,
                        sleep=lambda _seconds: None,
                    )

                self.assertTrue(result.restarted)
                self.assertEqual(result.method, "signal")
                self.assertEqual(result.previous_pid, 100)
                self.assertEqual(result.current_pid, 101)
                killer.assert_called_once_with(100, signal.SIGTERM)

    def test_restart_backend_service_does_not_signal_on_non_auth_restart_failure(self) -> None:
        responses = [
            CompletedProcessStub(returncode=0, stdout=RUNNING_STATUS),
            CompletedProcessStub(returncode=1, stderr="Failed to restart maverick-core.service: Unit not found.\n"),
            CompletedProcessStub(returncode=0, stdout=RUNNING_STATUS),
        ]

        def fake_runner(*args, **kwargs):
            return responses.pop(0)

        killer = Mock()

        with unittest.mock.patch("core.recovery.backend_service.urlopen", return_value=HealthResponse(200)):
            result = restart_backend_service(
                process_runner=fake_runner,
                process_killer=killer,
                sleep=lambda _seconds: None,
            )

        self.assertFalse(result.restarted)
        self.assertEqual(result.method, "systemctl")
        self.assertEqual(result.previous_pid, 100)
        self.assertEqual(result.current_pid, 100)
        killer.assert_not_called()

    def test_restart_backend_service_schedules_deferred_restart_when_running_inside_main_pid(self) -> None:
        responses = [
            CompletedProcessStub(returncode=0, stdout=f"MainPID={os.getpid()}\nRestart=always\nActiveState=active\nSubState=running\n"),
            CompletedProcessStub(returncode=1, stderr="Interactive authentication required.\n"),
        ]

        def fake_runner(*args, **kwargs):
            return responses.pop(0)

        killer = Mock()

        with (
            unittest.mock.patch("core.recovery.backend_service.urlopen", return_value=HealthResponse(200)),
            unittest.mock.patch("core.recovery.backend_service._schedule_delayed_sigterm") as schedule_restart,
        ):
            result = restart_backend_service(
                process_runner=fake_runner,
                process_killer=killer,
                sleep=lambda _seconds: None,
            )

        self.assertTrue(result.scheduled)
        self.assertTrue(result.restarted)
        self.assertEqual(result.method, "deferred-signal")
        killer.assert_not_called()
        schedule_restart.assert_called_once_with(os.getpid())
