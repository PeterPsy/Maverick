"""Bounded host-to-sidecar launch projection tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from core.apps.errors import AppHostingError
from core.apps.models import HttpSidecarHostPrepareSpec
from core.apps.sidecar_host_prepare import run_sidecar_host_prepare


class SidecarHostPrepareTests(unittest.TestCase):
    def test_runner_returns_only_the_exact_declared_environment_projection(self) -> None:
        repository = Path(__file__).resolve().parents[3]
        (repository / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=repository / "tmp") as temporary:
            source = Path(temporary)
            hook = source / "prepare.py"
            hook.write_text(
                "import json\n"
                "print(json.dumps({'ok': True, 'environment': "
                "{'MAVERICK_APP_SELECTION': 'digest-locked'}}))\n",
                encoding="utf-8",
            )
            declaration = HttpSidecarHostPrepareSpec(
                entrypoint="prepare.py",
                timeout_seconds=5,
                environment_keys=["MAVERICK_APP_SELECTION"],
            )

            projected = run_sidecar_host_prepare(
                source,
                declaration,
                payload={"workspace_id": "default"},
            )

            self.assertEqual(
                projected,
                {"MAVERICK_APP_SELECTION": "digest-locked"},
            )

    def test_runner_rejects_undeclared_output(self) -> None:
        repository = Path(__file__).resolve().parents[3]
        (repository / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=repository / "tmp") as temporary:
            source = Path(temporary)
            (source / "prepare.py").write_text(
                "print('{\"ok\":true,\"environment\":{\"MAVERICK_APP_EXTRA\":\"x\"}}')\n",
                encoding="utf-8",
            )
            declaration = HttpSidecarHostPrepareSpec(
                entrypoint="prepare.py",
                timeout_seconds=5,
                environment_keys=["MAVERICK_APP_SELECTION"],
            )

            with self.assertRaisesRegex(AppHostingError, "invalid projection"):
                run_sidecar_host_prepare(
                    source,
                    declaration,
                    payload={"workspace_id": "default"},
                )


if __name__ == "__main__":
    unittest.main()
