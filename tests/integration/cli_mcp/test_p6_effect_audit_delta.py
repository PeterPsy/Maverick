"""Executable regressions for the P6 built-in effect-audit delta.

Business-state reads may use the SDK's advisory lock; they must not seed,
repair, mutate pins or emit mutation events. Display projections are data,
not a new CLI/MCP authorization or a remote-data classification.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.app_sdk.display_models import project_display_model
from core.shared.entrypoints import run_json_entrypoint


ROOT = Path(__file__).resolve().parents[3]


class P6EffectAuditDeltaTest(unittest.TestCase):
    def test_app_store_pin_reads_do_not_seed_repair_or_emit_events_on_either_surface(self):
        app = ROOT / "apps/app-store"
        variants = (None, {"pinned_apps": ["chat", "temporarily-unavailable"]}, {"pinned_apps": "invalid"})
        for surface, entrypoint, selector in (
            ("cli", "cli/app_cli.py", {"command_id": "app-store"}),
            ("mcp", "mcp/server.py", {"tool_name": "app_store"}),
        ):
            for state in variants:
                with self.subTest(surface=surface, state=state), TemporaryDirectory() as directory:
                    data_root = Path(directory)
                    path = data_root / "state.json"
                    original = None if state is None else json.dumps(state).encode()
                    if original is not None:
                        path.write_bytes(original)
                    for action in ("pinned_apps.read", "pinned_apps.list"):
                        for _ in range(2):
                            response = run_json_entrypoint(app / entrypoint, cwd=app, payload={
                                **selector, "workspace_id": "default", "data_root": directory,
                                "arguments": {"action": action, "app_ids": ["overwrite-attempt"]},
                            })
                            self.assertEqual(response["status_code"], 200, response)
                            expected = ["chat"] if state is None else state["pinned_apps"]
                            self.assertEqual(response["pinned_apps"], expected if isinstance(expected, list) else [])
                            self.assertFalse(response.get("app_events"))
                            self.assertEqual(path.read_bytes() if path.exists() else None, original)
                            self.assertLessEqual({item.name for item in data_root.iterdir()},
                                                 {"state.json", ".state.json.lock"})

    def test_new_http_display_actions_do_not_expand_cli_or_mcp_read_enums(self):
        for app_id in ("calendar", "chat", "crm", "mail"):
            for relative in ("cli/command_schemas.json", "mcp/tool_schemas.json"):
                with self.subTest(app_id=app_id, descriptor=relative):
                    document = json.loads((ROOT / "apps" / app_id / relative).read_text())
                    self.assertNotIn("pwa.read_model", json.dumps(document))

    def test_reviewed_display_shapes_drop_unlisted_fields_and_privileged_map_keys(self):
        def sample(shape):
            value = {"credential_unknown": "MUST-NOT-PROJECT"}
            for key, kind in shape.get("fields", {}).items():
                value[key] = {"string": "display", "number": 1, "boolean": False, "strings": ["display"]}[kind]
            for key, child in shape.get("objects", {}).items():
                value[key] = sample(child)
            for key, child in shape.get("lists", {}).items():
                value[key] = [sample(child)]
            for key, kind in shape.get("maps", {}).items():
                value[key] = {"display": 1 if kind == "number" else "display", "access_token": "MUST-NOT-PROJECT"}
            return value

        for app_id in ("crm", "mail"):
            shapes = json.loads((ROOT / "apps" / app_id / "pwa_read_models.v1.json").read_text())
            for kind, shape in shapes.items():
                with self.subTest(app_id=app_id, kind=kind):
                    projected = project_display_model(sample(shape), shape)
                    self.assertNotIn("MUST-NOT-PROJECT", json.dumps(projected))


if __name__ == "__main__":
    unittest.main()
