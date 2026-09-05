"""Read-only HTTP pin discovery must be safe to repeat during shell recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BACKEND = Path(__file__).resolve().parents[1] / "backend" / "app_backend.py"


class PinnedAppsHttpReadTest(unittest.TestCase):
    def invoke(self, data_root: Path, extra_fields: dict | None = None) -> dict:
        result = subprocess.run(
            [sys.executable, str(BACKEND)],
            input=json.dumps({
                "method": "POST",
                "data_root": str(data_root),
                "body": {"action": "pinned_apps.read", **(extra_fields or {})},
                "workspace_apps": {"items": [{"app_id": "chat", "frontend_launchable": True}]},
            }),
            capture_output=True,
            env={**os.environ, "PYTHONPATH": str(BACKEND.parents[3])},
            text=True,
            check=True,
            timeout=15,
        )
        return json.loads(result.stdout)

    def test_repeated_read_preserves_stored_pins_without_registry_repair_or_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "state.json"
            original = json.dumps({"pinned_apps": ["chat", "crm", "mail", "temporarily-unavailable"]})
            path.write_text(original, encoding="utf-8")
            for _ in range(2):
                result = self.invoke(root)
                self.assertEqual(result["status_code"], 200)
                self.assertEqual(result["json"], json.loads(original))
                self.assertFalse(result.get("app_events"))
                self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_read_does_not_seed_business_state_when_no_pin_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.invoke(root)
            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["json"], {"pinned_apps": ["chat"]})
            self.assertFalse((root / "state.json").exists())

    def test_read_ignores_mutation_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.invoke(root, {"app_ids": ["mail"], "app_id": "mail"})
            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["json"], {"pinned_apps": ["chat"]})
            self.assertFalse((root / "state.json").exists())
