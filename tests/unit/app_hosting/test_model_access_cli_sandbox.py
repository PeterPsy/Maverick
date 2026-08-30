"""Concurrency proofs for the shared native-Codex technical home."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Lock
import tempfile
import time
import unittest
from unittest.mock import patch

from core.model_access import cli_sandbox
from core.model_access.models import ModelAccessScope


class ModelAccessCliSandboxTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
