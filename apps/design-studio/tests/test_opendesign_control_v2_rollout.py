from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = ROOT / "apps/design-studio/service"
sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_control_v2_rollout import (  # noqa: E402
    ControlV2RolloutError,
    convert_control_v1_to_v2,
)


RUNTIME = "a" * 64
PREVIOUS_RUNTIME = "b" * 64
WEB = "c" * 64
VERSION = "0.16.1"
GENERATION = "gen_current"
PREVIOUS_GENERATION = "gen_previous"
MIGRATION = "migration_existing"


class OpenDesignControlV2RolloutTests(unittest.TestCase):
    def test_converts_verified_v1_control_and_retires_old_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(Path(temporary))
            outcome = convert_control_v1_to_v2(
                root,
                expected_runtime_artifact_sha256=RUNTIME,
                web_overlay_sha256=WEB,
                expected_od_version=VERSION,
                verified_artifacts={RUNTIME: VERSION},
                verified_overlays={
                    WEB: {
                        "od_version": VERSION,
                        "compatible_runtime_artifact_sha256": [RUNTIME],
                    }
                },
                now=lambda: "2026-08-12T00:00:00Z",
            )
            self.assertTrue(outcome.converted)
            self.assertEqual(outcome.retired_migration_id, MIGRATION)
            payload = json.loads((root / "control.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "3")
            self.assertEqual(payload["active"]["runtime_artifact_sha256"], RUNTIME)
            self.assertEqual(payload["active"]["web_overlay_sha256"], WEB)
            self.assertIsNone(payload["previous_release"])
            self.assertIsNone(payload["migration_id"])

    def test_inconsistent_legacy_journal_fails_without_replacing_control(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(Path(temporary))
            journal_path = root / "migrations" / f"{MIGRATION}.json"
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            journal["target"]["data_generation"] = "gen_wrong"
            journal_path.write_text(json.dumps(journal), encoding="utf-8")
            before = (root / "control.json").read_bytes()
            with self.assertRaises(ControlV2RolloutError):
                convert_control_v1_to_v2(
                    root,
                    expected_runtime_artifact_sha256=RUNTIME,
                    web_overlay_sha256=WEB,
                    expected_od_version=VERSION,
                    verified_artifacts={RUNTIME: VERSION},
                    verified_overlays={},
                )
            self.assertEqual((root / "control.json").read_bytes(), before)

    @staticmethod
    def _root(parent: Path) -> Path:
        root = parent / "opendesign"
        for relative in (
            "instances/gen_current/data",
            "instances/gen_previous/data",
            f"backups/{MIGRATION}",
            "migrations",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        active = {
            "bundle_artifact_sha256": RUNTIME,
            "od_version": VERSION,
            "data_generation": GENERATION,
        }
        previous = {
            "bundle_artifact_sha256": PREVIOUS_RUNTIME,
            "od_version": VERSION,
            "data_generation": PREVIOUS_GENERATION,
        }
        (root / "control.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "active": active,
                    "previous": previous,
                    "migration_id": MIGRATION,
                    "updated_at": "2026-08-11T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        (root / "migrations" / f"{MIGRATION}.json").write_text(
            json.dumps(
                {
                    "schema_version": "1",
                    "migration_id": MIGRATION,
                    "state": "cutover_committed",
                    "source": previous,
                    "target": active,
                    "source_snapshot": f"backups/{MIGRATION}",
                    "checks": {},
                    "created_at": "2026-08-11T00:00:00Z",
                    "updated_at": "2026-08-11T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        return root


if __name__ == "__main__":
    unittest.main()
