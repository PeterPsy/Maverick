from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from core.providers.certification_manifests import (
    GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
    OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
)
from core.providers.certified_execution_tcb import (
    CERTIFIED_EXECUTION_TCB,
    certified_tcb_identity,
    compute_certified_tcb_digest,
)


class CertifiedExecutionTcbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]

    def test_every_suite_derives_artifacts_and_identity_from_one_manifest(self) -> None:
        identity = certified_tcb_identity(self.root)
        for manifest in (
            GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
            OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
        ):
            with self.subTest(provider_id=manifest.provider_id):
                self.assertEqual(manifest.artifact_paths, CERTIFIED_EXECUTION_TCB.artifact_paths)
                self.assertEqual(manifest.tcb_manifest_id, identity.manifest_id)
                self.assertEqual(manifest.tcb_manifest_version, identity.manifest_version)
                self.assertEqual(manifest.tcb_structure_digest, identity.structure_digest)
                self.assertEqual(
                    tuple(step.kind for step in manifest.steps),
                    ("fixture_contract", "live_probe"),
                )

    def test_drift_in_each_execution_boundary_changes_the_live_digest(self) -> None:
        baseline = compute_certified_tcb_digest(self.root)
        components = {
            component.component_id: component
            for component in CERTIFIED_EXECUTION_TCB.components
        }
        targets = {
            "runtime_api": "core/api/runtime_api.py",
            "classifier": "core/egress/classification.py",
            "input_composition": "core/runtime/provider_input_context.py",
            "ledger": "core/runtime/tool_ledger.py",
            "runtime_store": "core/runtime/store.py",
            "lifecycle": "core/runtime/lifecycle_service.py",
            "chat_ui_governance": f"{components['chat-governance'].paths[0]}/App.tsx",
            "settings_ui_governance": (
                f"{components['settings-governance'].paths[0]}/settingsPanel.ts"
            ),
        }
        original_read_bytes = Path.read_bytes
        for boundary, relative_path in targets.items():
            target = (self.root / relative_path).resolve(strict=True)

            def drifted_read_bytes(path: Path, *, _target: Path = target) -> bytes:
                content = original_read_bytes(path)
                if path.resolve() == _target:
                    return content + b"\n# certified-tcb-drift-fixture\n"
                return content

            with self.subTest(boundary=boundary), patch.object(
                Path,
                "read_bytes",
                drifted_read_bytes,
            ):
                self.assertNotEqual(compute_certified_tcb_digest(self.root), baseline)


if __name__ == "__main__":
    unittest.main()
