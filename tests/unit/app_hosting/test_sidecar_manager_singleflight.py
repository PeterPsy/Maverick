"""Concurrency proofs for governed HTTP sidecar startup."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.api import sidecar_proxy
from core.api.sidecar_proxy import HttpSidecarManager, SidecarStartupError
from core.apps.contracts import build_http_sidecar_spec


class _LiveProcess:
    returncode = None

    @staticmethod
    def poll() -> None:
        return None


class _Running:
    def __init__(self, instance_id: str) -> None:
        self.instance_id = instance_id
        self.process = _LiveProcess()


class HttpSidecarManagerSingleflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = HttpSidecarManager()
        self.sidecar = build_http_sidecar_spec(service_id="daemon", command=["python3", "server.py"])
        with sidecar_proxy._AUTO_REPAIR_LOCK:
            sidecar_proxy._AUTO_REPAIRS.clear()
            sidecar_proxy._AUTO_REPAIR_BACKOFFS.clear()

    def test_same_key_shares_exactly_one_startup(self) -> None:
        entered = Event()
        release = Event()
        running = _Running("shared")

        def start(**_kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return running

        self.manager._start_sidecar = Mock(side_effect=start)  # type: ignore[method-assign]
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self._ensure, app_id="one", data_root="/data/one")
            self.assertTrue(entered.wait(1))
            second = pool.submit(self._ensure, app_id="one", data_root="/data/one")
            release.set()
            self.assertIs(first.result(timeout=2), running)
            self.assertIs(second.result(timeout=2), running)
        self.assertEqual(self.manager._start_sidecar.call_count, 1)  # type: ignore[attr-defined]

    def test_different_keys_start_in_parallel(self) -> None:
        rendezvous = Barrier(2, timeout=2)
        active = 0
        peak = 0
        guard = Lock()

        def start(**kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            rendezvous.wait()
            with guard:
                active -= 1
            return _Running(str(kwargs["app_id"]))

        self.manager._start_sidecar = Mock(side_effect=start)  # type: ignore[method-assign]
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(self._ensure, app_id="one", data_root="/data/one")
            two = pool.submit(self._ensure, app_id="two", data_root="/data/two")
            self.assertEqual(one.result(timeout=3).instance_id, "one")
            self.assertEqual(two.result(timeout=3).instance_id, "two")
        self.assertEqual(peak, 2)

    def test_slow_startup_does_not_convoy_another_sidecar(self) -> None:
        slow_entered = Event()
        slow_release = Event()

        def start(**kwargs):
            if kwargs["app_id"] == "slow":
                slow_entered.set()
                self.assertTrue(slow_release.wait(2))
            return _Running(str(kwargs["app_id"]))

        self.manager._start_sidecar = Mock(side_effect=start)  # type: ignore[method-assign]
        with ThreadPoolExecutor(max_workers=2) as pool:
            slow = pool.submit(self._ensure, app_id="slow", data_root="/data/slow")
            self.assertTrue(slow_entered.wait(1))
            fast = pool.submit(self._ensure, app_id="fast", data_root="/data/fast")
            self.assertEqual(fast.result(timeout=1).instance_id, "fast")
            slow_release.set()
            self.assertEqual(slow.result(timeout=2).instance_id, "slow")

    def test_stop_cancels_inflight_startup_and_leaves_no_poisoned_future(self) -> None:
        entered = Event()

        def start(**kwargs):
            entered.set()
            cancel_event = kwargs["cancel_event"]
            self.assertTrue(cancel_event.wait(2))
            raise SidecarStartupError("startup_cancelled", "health_wait", "cancelled")

        self.manager._start_sidecar = Mock(side_effect=start)  # type: ignore[method-assign]
        with ThreadPoolExecutor(max_workers=1) as pool:
            startup = pool.submit(self._ensure, app_id="one", data_root="/data/one")
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.manager.stop_app(workspace_id="default", app_id="one"), 1)
            with self.assertRaisesRegex(SidecarStartupError, "cancelled"):
                startup.result(timeout=2)
        self.assertFalse(self.manager._starting)
        self.assertFalse(self.manager._running)

    def test_failed_startup_is_removed_and_next_request_can_retry(self) -> None:
        attempts = 0

        def start(**_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise SidecarStartupError("daemon_ready_timeout", "health_wait", "not ready")
            return _Running("retry")

        self.manager._start_sidecar = Mock(side_effect=start)  # type: ignore[method-assign]
        with self.assertRaises(SidecarStartupError):
            self._ensure(app_id="one", data_root="/data/one")
        self.assertEqual(self._ensure(app_id="one", data_root="/data/one").instance_id, "retry")
        self.assertEqual(attempts, 2)

    def test_existing_process_is_rechecked_and_evicted_when_transactional_health_is_lost(self) -> None:
        running = _Running("stale-ready")
        self.manager._start_sidecar = Mock(return_value=running)  # type: ignore[method-assign]
        self.assertIs(self._ensure(app_id="one", data_root="/data/one"), running)
        failure = SidecarStartupError(
            "activation_incomplete",
            "health_recheck",
            "not transactionally ready",
        )

        with (
            patch.object(sidecar_proxy, "_probe_sidecar_health", side_effect=failure) as probe,
            patch.object(self.manager, "_cleanup_sidecar") as cleanup,
            self.assertRaises(SidecarStartupError) as raised,
        ):
            self.manager.ensure_running(
                workspace_id="default",
                app_id="one",
                source_root=Path("/apps/one"),
                data_root="/data/one",
                sidecar=self.sidecar,
                start_path=Path("/repo"),
                shutdown_controller=None,
                verify_existing_health=True,
            )

        self.assertEqual(raised.exception.code, "activation_incomplete")
        probe.assert_called_once_with(running, sidecar=self.sidecar)
        cleanup.assert_called_once_with(running)
        self.assertFalse(self.manager._running)
        status = self.manager.startup_status(
            workspace_id="default",
            app_id="one",
            sidecar_id="daemon",
            data_root="/data/one",
        )
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["last_failure"]["code"], "activation_incomplete")

    def test_failed_auto_repair_enters_backoff_without_a_spawn_hash_retry_loop(self) -> None:
        binding = SimpleNamespace(
            workspace_id="default",
            app_id="design-studio",
            data_root="/data/design-studio",
            source_kind="builtin",
            source_record_id="design-studio",
        )
        parsed = SimpleNamespace(contract=SimpleNamespace())
        hook = Mock(side_effect=RuntimeError("repair failed"))
        with (
            patch.object(sidecar_proxy, "_build_workspace_hook_payload", return_value={}),
            patch.object(sidecar_proxy, "run_lifecycle_hook", hook),
        ):
            with self.assertRaises(SidecarStartupError) as first:
                sidecar_proxy._run_declared_artifact_repair_singleflight(
                    binding=binding,
                    source_root=Path("/apps/design-studio"),
                    parsed=parsed,
                    sidecar=self.sidecar,
                    start_path=Path("/repo"),
                )
            with self.assertRaises(SidecarStartupError) as second:
                sidecar_proxy._run_declared_artifact_repair_singleflight(
                    binding=binding,
                    source_root=Path("/apps/design-studio"),
                    parsed=parsed,
                    sidecar=self.sidecar,
                    start_path=Path("/repo"),
                )

        self.assertEqual(first.exception.phase, "artifact_repair")
        self.assertEqual(second.exception.phase, "artifact_repair_backoff")
        hook.assert_called_once()

    def _ensure(self, *, app_id: str, data_root: str):
        return self.manager.ensure_running(
            workspace_id="default",
            app_id=app_id,
            source_root=Path("/apps") / app_id,
            data_root=data_root,
            sidecar=self.sidecar,
            start_path=Path("/repo"),
            shutdown_controller=None,
        )


if __name__ == "__main__":
    unittest.main()
