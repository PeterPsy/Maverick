"""The common SDK reference surface does not require a browser runtime."""

from pathlib import Path
import tempfile
import unittest
from core.shared.entrypoints import run_json_entrypoint


class BrowserReferenceManifestTest(unittest.TestCase):
    def test_manifest_is_empty_and_needs_no_broker_or_credentials(self):
        app_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = run_json_entrypoint(
                app_root / "mcp/server.py",
                cwd=app_root,
                payload={
                    "app_id": "browser",
                    "workspace_id": "default",
                    "data_root": directory,
                    "tool_name": "browser_reference_manifest",
                    "arguments": {},
                    "effective_mode": "full_access",
                },
            )
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["entity_types"], [])
        self.assertEqual(result["app_events"], [])
