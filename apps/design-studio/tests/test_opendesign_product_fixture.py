"""Source-binding checks for the synthetic Design Studio release installation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = (
    ROOT / "apps/design-studio/tests/fixtures/opendesign_product_server.py"
)


def _load_fixture():
    spec = importlib.util.spec_from_file_location(
        "opendesign_product_server_fixture",
        FIXTURE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class OpenDesignProductFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = _load_fixture()

    def test_synthetic_installation_binds_hooks_to_the_attested_core_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="opendesign-product-fixture-") as temporary:
            installation = Path(temporary)
            self.fixture._prepare_root(installation)

            self.assertTrue((installation / "core").is_symlink())
            self.assertEqual((installation / "core").resolve(), ROOT / "core")
            self.assertTrue((installation / "scripts").is_symlink())
            self.assertEqual((installation / "scripts").resolve(), ROOT / "scripts")
            design_studio = installation / "apps/design-studio"
            self.assertTrue(design_studio.is_dir())
            self.assertFalse(design_studio.is_symlink())
            contract = json.loads(
                (design_studio / "app_contract.json").read_text(encoding="utf-8")
            )
            environment = contract["services"]["http_sidecars"][0]["env"]
            self.assertEqual(
                environment["MAVERICK_OPENDESIGN_FAILURE_INJECTION_ROOT"],
                "${app.data_dir}/opendesign/.maverick-failure-injection",
            )


if __name__ == "__main__":
    unittest.main()
