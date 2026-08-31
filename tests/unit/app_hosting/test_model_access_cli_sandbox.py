"""Concurrency proofs for the shared native-Codex technical home."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Event, Lock
import tempfile
import time
import unittest
from unittest.mock import patch

from core.model_access import cli_sandbox
from core.model_access.cancellation import (
    ModelAccessCancellation,
    ModelAccessRequestCancelled,
)
from core.model_access.models import ModelAccessReadOnlyMount, ModelAccessScope


class ModelAccessCliSandboxTests(unittest.TestCase):
    def test_sandbox_binds_only_requested_artifact_directories_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o555)
            bwrap = root / "bwrap"
            bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
            bwrap.chmod(0o555)
            data_root = root / "data"
            cli_home = root / "codex-home"
            artifact_root = root / "opendesign"
            skills_root = (
                artifact_root / "official" / "release" / "rootfs" / "app" / "skills"
            )
            data_root.mkdir()
            cli_home.mkdir()
            skills_root.mkdir(parents=True)
            target = Path(
                "/artifacts/opendesign/official/release/rootfs/app/skills"
            )

            with patch.object(cli_sandbox.shutil, "which", return_value=str(bwrap)):
                command = cli_sandbox.codex_sandbox_command(
                    executable=executable,
                    data_root=data_root,
                    inner_cwd="/workspace",
                    cli_home=cli_home,
                    argv=("--version",),
                    read_only_mounts=(
                        ModelAccessReadOnlyMount(
                            source=skills_root,
                            target=target,
                        ),
                    ),
                    authorized_read_only_mounts=(
                        ModelAccessReadOnlyMount(
                            source=artifact_root,
                            target=Path("/artifacts/opendesign"),
                        ),
                    ),
                )

            self.assertIn("/artifacts", command)
            self.assertIn(target.as_posix(), command)
            bind_index = command.index(skills_root.resolve().as_posix())
            self.assertEqual(
                command[bind_index - 1 : bind_index + 2],
                ["--ro-bind", skills_root.resolve().as_posix(), target.as_posix()],
            )
            self.assertNotIn(artifact_root.as_posix(), command)
            with (
                patch.object(cli_sandbox.shutil, "which", return_value=str(bwrap)),
                self.assertRaisesRegex(PermissionError, "lease-authorized"),
            ):
                cli_sandbox.codex_sandbox_command(
                    executable=executable,
                    data_root=data_root,
                    inner_cwd="/workspace",
                    cli_home=cli_home,
                    argv=("--version",),
                    read_only_mounts=(
                        ModelAccessReadOnlyMount(
                            source=skills_root,
                            target=target,
                        ),
                    ),
                )

    def test_concurrent_home_preparation_uses_unique_temps_under_one_home_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_home = root / "source-codex"
            source_home.mkdir()
            (source_home / "auth.json").write_text('{"token":"technical"}\n', encoding="utf-8")
            scope = ModelAccessScope(
                workspace_id="default",
                app_id="design-studio",
                sidecar_id="opendesign",
                data_root=root / "native",
                api=True,
                cli=("codex",),
            )
            scope.data_root.mkdir()
            original = cli_sandbox._atomic_private_write
            state_lock = Lock()
            active = 0
            maximum_active = 0

            def observed_write(destination: Path, body: bytes) -> None:
                nonlocal active, maximum_active
                with state_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    time.sleep(0.005)
                    original(destination, body)
                finally:
                    with state_lock:
                        active -= 1

            with (
                patch.dict(
                    os.environ,
                    {"MAVERICK_MODEL_ACCESS_CODEX_HOME": str(source_home)},
                    clear=False,
                ),
                patch.object(cli_sandbox, "_atomic_private_write", side_effect=observed_write),
                ThreadPoolExecutor(max_workers=12) as pool,
            ):
                homes = list(pool.map(lambda _index: cli_sandbox.prepare_codex_home(root, scope), range(24)))

            self.assertEqual(len(set(homes)), 1)
            home = homes[0]
            self.assertEqual((home / "auth.json").read_text(encoding="utf-8"), '{"token":"technical"}\n')
            self.assertIn('trust_level = "trusted"', (home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(maximum_active, 1)
            self.assertEqual(list(home.glob(".*.tmp")), [])

    def test_complete_invocations_are_serialized_on_the_shared_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "codex-home"
            home.mkdir()
            state_lock = Lock()
            active = 0
            maximum_active = 0

            def invocation(_index: int) -> None:
                nonlocal active, maximum_active
                with cli_sandbox.codex_home_lock(home):
                    with state_lock:
                        active += 1
                        maximum_active = max(maximum_active, active)
                    try:
                        time.sleep(0.005)
                    finally:
                        with state_lock:
                            active -= 1

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(invocation, range(16)))

            self.assertEqual(maximum_active, 1)

    def test_cancelled_home_preparation_stops_waiting_for_the_shared_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_home = root / "source-codex"
            source_home.mkdir()
            (source_home / "auth.json").write_text("{}\n", encoding="utf-8")
            scope = ModelAccessScope(
                workspace_id="default",
                app_id="design-studio",
                sidecar_id="opendesign",
                data_root=root / "native",
                api=True,
                cli=("codex",),
            )
            scope.data_root.mkdir()
            shared_home = (
                root
                / "tmp/model-access/state/default/design-studio/codex-home"
            )
            shared_home.mkdir(parents=True)
            cancellation = ModelAccessCancellation()
            started = Event()

            def prepare() -> Path:
                started.set()
                return cli_sandbox.prepare_codex_home(
                    root,
                    scope,
                    cancellation=cancellation,
                )

            with (
                patch.dict(
                    os.environ,
                    {"MAVERICK_MODEL_ACCESS_CODEX_HOME": str(source_home)},
                    clear=False,
                ),
                cli_sandbox.codex_home_lock(shared_home),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                future = pool.submit(prepare)
                self.assertTrue(started.wait(1))
                time.sleep(0.05)
                cancellation.set()
                with self.assertRaises(ModelAccessRequestCancelled):
                    future.result(timeout=0.5)

    def test_cancelled_invocation_stops_waiting_for_the_shared_home_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "codex-home"
            home.mkdir()
            cancellation = ModelAccessCancellation()
            started = Event()

            def wait_for_invocation_lock() -> None:
                started.set()
                with cli_sandbox.codex_home_lock(
                    home,
                    cancellation=cancellation,
                ):
                    raise AssertionError("cancelled waiter acquired the lock")

            with (
                cli_sandbox.codex_home_lock(home),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                future = pool.submit(wait_for_invocation_lock)
                self.assertTrue(started.wait(1))
                time.sleep(0.05)
                cancellation.set()
                with self.assertRaises(ModelAccessRequestCancelled):
                    future.result(timeout=0.5)


if __name__ == "__main__":
    unittest.main()
