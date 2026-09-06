"""A terminated launcher may still have a TERM-ignoring child holding stdout."""

import os
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest import TestCase, mock

from core.runtime.hosted_process_termination import terminate_hosted_process
from core.runtime.tool_errors import RuntimeToolError


_CHILD = """
import os, signal, time
if os.fork() == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.write(1, b'ready\\n')
    time.sleep(30)
else:
    signal.pause()
"""


class HostedProcessTerminationTest(TestCase):
    def start_group(self):
        process = subprocess.Popen(
            [sys.executable, "-c", _CHILD], start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.addCleanup(self.cleanup_group, process)
        self.assertEqual(process.stdout.readline(), b"ready\n")
        return process

    @staticmethod
    def cleanup_group(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=2)

    def test_child_is_killed_even_when_term_exits_the_launcher(self):
        process = self.start_group()
        self.assertTrue(terminate_hosted_process(process))
        self.assertEqual(process.communicate(timeout=1)[0], b"")

    def test_reaped_handle_cannot_signal_a_reused_numeric_process_group(self):
        with mock.patch("core.runtime.hosted_process_termination.os.killpg") as signal_group:
            self.assertFalse(terminate_hosted_process(SimpleNamespace(pid=123, poll=lambda: 0)))
        signal_group.assert_not_called()

    def test_signal_failure_never_claims_success(self):
        with mock.patch("core.runtime.hosted_process_termination.os.killpg", side_effect=PermissionError), self.assertRaisesRegex(
            RuntimeToolError, "hosted_process_termination_failed",
        ):
            terminate_hosted_process(SimpleNamespace(pid=123, poll=lambda: None))
