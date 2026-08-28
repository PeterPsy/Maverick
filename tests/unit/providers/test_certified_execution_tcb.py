from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from core.providers.certification_manifests import (
    GOOGLE_AGENTIC_CERTIFICATION_MANIFEST,
    OPENROUTER_AGENTIC_CERTIFICATION_MANIFEST,
)
from core.providers.certified_execution_tcb import (
    CERTIFIED_EXECUTION_TCB,
    audit_certified_tcb_dependencies,
    certified_tcb_identity,
    compute_certified_tcb_digest,
)
from core.providers.errors import CapabilityCertificateError


class CertifiedExecutionTcbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]

    def test_every_suite_derives_artifacts_and_identity_from_one_manifest(self) -> None:
        identity = certified_tcb_identity(self.root)
        self.assertEqual(identity.manifest_version, "9")
        self.assertEqual(
            identity.structure_digest,
            "87cac5cfec4627eda241b5c279382640965477f67dfbca005f20a8f863c73ab6",
        )
        self.assertIn(
            "scripts/run_google_interactions_probe.py",
            CERTIFIED_EXECUTION_TCB.artifact_paths,
        )
        self.assertIn(
            "scripts/run_openrouter_agentic_probe.py",
            CERTIFIED_EXECUTION_TCB.artifact_paths,
        )
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

    def test_security_dependency_contracts_cover_the_known_transitive_graph(self) -> None:
        report = audit_certified_tcb_dependencies(self.root)

        self.assertEqual(
            report.contract_ids,
            (
                "runtime-admission",
                "provider-input-composition",
                "classification-egress",
                "tool-execution",
                "provider-state-lifecycle",
                "served-governance",
            ),
        )
        self.assertIn(
            (
                "core/runtime/provider_input_context.py",
                "core/inter_agent/generalist_context.py",
            ),
            report.import_edges,
        )
        for dependency in (
            "core/__init__.py",
            "core/inter_agent/__init__.py",
            "core/inter_agent/generalist_context.py",
            "core/inter_agent/orchestration_state.py",
            "core/inter_agent/service.py",
            "core/recovery/continuation_admission.py",
            "core/shared/entrypoints.py",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, report.audited_paths)

    def test_dependency_audit_rejects_a_new_uncovered_transitive_import(self) -> None:
        target = (self.root / "core/runtime/provider_input_context.py").resolve()
        original_read_text = Path.read_text

        def import_uncovered_dependency(
            path: Path,
            *args: object,
            **kwargs: object,
        ) -> str:
            content = original_read_text(path, *args, **kwargs)
            if path.resolve() == target:
                return content + "\nfrom core.inter_agent.executor import InterAgentExecutor\n"
            return content

        with patch.object(Path, "read_text", import_uncovered_dependency):
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certificate_tcb_transitive_dependency_uncovered",
            ):
                audit_certified_tcb_dependencies(self.root)

    def test_live_digest_reaudits_a_new_source_identity_before_returning(self) -> None:
        target = (self.root / "core/runtime/provider_input_context.py").resolve()
        original_read_bytes = Path.read_bytes
        original_read_text = Path.read_text
        extra_import = "\nfrom core.inter_agent.executor import InterAgentExecutor\n"

        def changed_read_bytes(path: Path) -> bytes:
            content = original_read_bytes(path)
            return content + extra_import.encode() if path.resolve() == target else content

        def changed_read_text(
            path: Path,
            *args: object,
            **kwargs: object,
        ) -> str:
            content = original_read_text(path, *args, **kwargs)
            return content + extra_import if path.resolve() == target else content

        with patch.object(Path, "read_bytes", changed_read_bytes), patch.object(
            Path,
            "read_text",
            changed_read_text,
        ):
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certificate_tcb_transitive_dependency_uncovered",
            ):
                compute_certified_tcb_digest(self.root)

    def test_dependency_audit_rejects_a_manifest_that_drops_the_known_closure(self) -> None:
        components = tuple(
            replace(
                component,
                paths=tuple(
                    path
                    for path in component.paths
                    if not path.startswith("core/inter_agent")
                ),
            )
            for component in CERTIFIED_EXECUTION_TCB.components
        )
        incomplete_manifest = replace(CERTIFIED_EXECUTION_TCB, components=components)

        with self.assertRaisesRegex(
            CapabilityCertificateError,
            "certificate_tcb_transitive_dependency_uncovered",
        ):
            audit_certified_tcb_dependencies(
                self.root,
                manifest=incomplete_manifest,
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
            "generalist_context": "core/inter_agent/generalist_context.py",
            "continuation_admission": "core/recovery/continuation_admission.py",
            "app_runtime_entrypoint": "core/shared/entrypoints.py",
            "python_package_initializer": "core/__init__.py",
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
