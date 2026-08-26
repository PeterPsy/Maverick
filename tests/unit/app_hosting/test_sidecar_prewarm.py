"""Concurrency and shutdown proofs for declarative sidecar prewarm."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.api import sidecar_prewarm


class _Shutdown:
    def __init__(self) -> None:
        self.stopping = False

    def is_shutting_down(self) -> bool:
        return self.stopping


def _arguments(*, workspace_id: str, app_id: str, sidecar_id: str, shutdown=None):
    return {
        "binding": SimpleNamespace(workspace_id=workspace_id, app_id=app_id),
        "source_root": object(),
        "parsed": object(),
        "sidecar": SimpleNamespace(service_id=sidecar_id),
        "start_path": object(),
        "shutdown_controller": shutdown,
        "trigger": "core_start",
    }


class SidecarPrewarmTests(unittest.TestCase):
    def setUp(self) -> None:
        with sidecar_prewarm._prewarm_family_guard:
            sidecar_prewarm._prewarm_family_locks.clear()

    def test_same_family_is_serialized_across_workspaces(self) -> None:
        active = 0
        peak = 0
        guard = Lock()

        def ensure(**_kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.04)
            with guard:
                active -= 1
            return SimpleNamespace(instance_id="ready")

        with patch.object(sidecar_prewarm, "ensure_sidecar_with_declared_auto_repair", side_effect=ensure):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(sidecar_prewarm._prewarm_one, **_arguments(
                        workspace_id=workspace,
                        app_id="design-studio",
                        sidecar_id="opendesign",
                    ))
                    for workspace in ("default", "workspace-b")
                ]
                for future in futures:
                    future.result(timeout=2)

        self.assertEqual(peak, 1)

    def test_core_start_prewarms_only_active_user_workspace_selections(self) -> None:
        workspaces = [
            SimpleNamespace(workspace_id="default", status="active"),
            SimpleNamespace(workspace_id="workspace-b", status="active"),
            SimpleNamespace(workspace_id="retired", status="disabled"),
        ]
        selections = {
            "user-active": SimpleNamespace(workspace_id="default"),
            "user-disabled": SimpleNamespace(workspace_id="workspace-b"),
        }
        state = SimpleNamespace(
            workspace_store=SimpleNamespace(
                list_workspaces=lambda: workspaces,
                get_active_workspace=lambda user_id: selections.get(user_id),
            ),
            identity_store=SimpleNamespace(
                list_users=lambda: [
                    SimpleNamespace(user_id="user-active", is_active=True),
                    SimpleNamespace(user_id="user-disabled", is_active=False),
                ]
            ),
        )

        selected = sidecar_prewarm._selected_core_start_workspaces(state)

        self.assertEqual([workspace.workspace_id for workspace in selected], ["default"])

    def test_core_start_uses_one_deterministic_fallback_without_user_selection(self) -> None:
        state = SimpleNamespace(
            workspace_store=SimpleNamespace(
                list_workspaces=lambda: [
                    SimpleNamespace(workspace_id="workspace-b", status="active"),
                    SimpleNamespace(workspace_id="default", status="active"),
                ],
                get_active_workspace=lambda _user_id: None,
            ),
            identity_store=SimpleNamespace(list_users=lambda: []),
        )

        selected = sidecar_prewarm._selected_core_start_workspaces(state)

        self.assertEqual([workspace.workspace_id for workspace in selected], ["default"])

    def test_different_sidecar_families_prewarm_in_parallel(self) -> None:
        rendezvous = Barrier(2, timeout=2)

        def ensure(**_kwargs):
            rendezvous.wait()
            return SimpleNamespace(instance_id="ready")

        with patch.object(sidecar_prewarm, "ensure_sidecar_with_declared_auto_repair", side_effect=ensure):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(
                    sidecar_prewarm._prewarm_one,
                    **_arguments(workspace_id="default", app_id="design-studio", sidecar_id="opendesign"),
                )
                second = pool.submit(
                    sidecar_prewarm._prewarm_one,
                    **_arguments(workspace_id="default", app_id="other", sidecar_id="daemon"),
                )
                first.result(timeout=3)
                second.result(timeout=3)

    def test_shutdown_while_waiting_for_family_lock_never_spawns(self) -> None:
        shutdown = _Shutdown()
        lock = sidecar_prewarm._prewarm_family_lock("design-studio", "opendesign")
        entered = Event()
        ensure = Mock(return_value=SimpleNamespace(instance_id="unexpected"))

        lock.acquire()
        try:
            with patch.object(sidecar_prewarm, "ensure_sidecar_with_declared_auto_repair", ensure):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        sidecar_prewarm._prewarm_one,
                        **_arguments(
                            workspace_id="default",
                            app_id="design-studio",
                            sidecar_id="opendesign",
                            shutdown=shutdown,
                        ),
                    )
                    entered.set()
                    self.assertTrue(entered.wait(1))
                    shutdown.stopping = True
                    lock.release()
                    future.result(timeout=2)
        finally:
            if lock.locked():
                lock.release()

        ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
