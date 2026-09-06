"""Concurrent cold behavior checks must not reap each other's synthetic workers."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, local
from unittest import TestCase, mock

from core.runtime import hosted_shell_process_behavior as behavior


class HostedShellProbeIsolationTest(TestCase):
    def test_cleanup_cannot_kill_another_in_flight_behavior_probe(self):
        delayed_ready = Event()
        first_finished = Event()
        thread = local()
        session_ids = {}
        invoke = behavior.invoke_behavior_capability

        def controlled_invoke(capabilities, handle, arguments, context, **kwargs):
            session_ids[thread.role] = context.session_id
            if handle == "core-capability:process.interrupt" and thread.role == "delayed":
                delayed_ready.set()
                if not first_finished.wait(10):
                    raise AssertionError("Other behavior probe did not finish its cleanup.")
            return invoke(capabilities, handle, arguments, context, **kwargs)

        def run_delayed():
            thread.role = "delayed"
            return behavior.inspect_hosted_shell_process_behavior.__wrapped__()

        def run_first():
            thread.role = "first"
            try:
                if not delayed_ready.wait(10):
                    raise AssertionError("Delayed behavior probe did not reach interrupt.")
                return behavior.inspect_hosted_shell_process_behavior.__wrapped__()
            finally:
                first_finished.set()

        with mock.patch.object(behavior, "invoke_behavior_capability", side_effect=controlled_invoke):
            with ThreadPoolExecutor(max_workers=2) as workers:
                delayed = workers.submit(run_delayed)
                first = workers.submit(run_first)
                self.assertEqual(first.result(timeout=20), behavior.HOSTED_SHELL_PROCESS_BEHAVIOR_IDS)
                self.assertEqual(delayed.result(timeout=20), behavior.HOSTED_SHELL_PROCESS_BEHAVIOR_IDS)
        self.assertNotEqual(session_ids["first"], session_ids["delayed"])
