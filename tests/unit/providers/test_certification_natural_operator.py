from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from core.providers.agentic_models import WorkspaceAgenticProfileBinding
from core.providers.capability_models import CapabilityCertificateStatus
from core.providers.certification_natural_artifacts import write_new_json
from core.providers.certification_natural_fixtures import (
    materialize_openrouter_natural_fixtures,
)
from core.providers.certification_natural_scenarios import (
    OPENROUTER_NATURAL_PROMPTS,
    openrouter_natural_scenario_checks,
)
from core.providers.certification_openrouter_release import (
    activate_certified_openrouter_release,
)
from core.providers.openrouter_agentic_profile import (
    openrouter_agentic_preview_publication,
)


class CertificationNaturalOperatorTest(unittest.TestCase):
    def test_fixtures_and_prompts_are_version_independent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = materialize_openrouter_natural_fixtures(root)

            self.assertEqual(
                (root / "targeted_edit.txt").read_text(),
                "ALPHA_NATURAL\nPRESERVE_NATURAL\n",
            )
            self.assertEqual(skill.local_skill_id, "natural-inspection")
            self.assertNotIn("R67", "\n".join(OPENROUTER_NATURAL_PROMPTS.values()))

    def test_prompt_injection_check_requires_no_effect_and_stable_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materialize_openrouter_natural_fixtures(root)
            checks = openrouter_natural_scenario_checks(
                "prompt_injection",
                outputs=["INJECTION_REJECTED_NATURAL"],
                invocations=[],
                journals=[],
                workspace_root=root,
                before="a" * 64,
                after="a" * 64,
                authority_digests=["b" * 64],
                reloaded=False,
                failure_reasons=[None],
            )
            self.assertEqual(
                checks,
                {"authority_unchanged": True, "egress_enforced": True},
            )
            (root / "forbidden.txt").write_text("unexpected")
            self.assertFalse(
                openrouter_natural_scenario_checks(
                    "prompt_injection",
                    outputs=["INJECTION_REJECTED_NATURAL"],
                    invocations=[],
                    journals=[],
                    workspace_root=root,
                    before="a" * 64,
                    after="a" * 64,
                    authority_digests=["b" * 64],
                    reloaded=False,
                    failure_reasons=[None],
                )["egress_enforced"]
            )

    def test_artifacts_are_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "artifact.json"
            digest = write_new_json(output, {"safe": True})
            self.assertEqual(len(digest), 64)
            with self.assertRaises(FileExistsError):
                write_new_json(output, {"safe": False})

    def test_release_enables_only_openrouter_and_preserves_codex_default(self) -> None:
        now = datetime(2026, 9, 13, tzinfo=UTC)
        profile = openrouter_agentic_preview_publication(now=now).profile
        codex_profile = SimpleNamespace(model_provider_id="codex")
        old_profile = SimpleNamespace(model_provider_id="openrouter")
        codex = _binding(
            "codex-default",
            "codex-profile",
            "15",
            profile,
            now,
            is_default=True,
        )
        old_openrouter = _binding(
            "old-openrouter",
            "old-openrouter-profile",
            "6",
            profile,
            now,
        )
        bindings = [codex, old_openrouter]
        store = MagicMock()
        store.list_workspace_agentic_profile_bindings.side_effect = (
            lambda workspace_id: list(bindings)
        )
        store.get_agentic_profile_definition.side_effect = lambda identity, revision: {
            ("codex-profile", "15"): codex_profile,
            ("old-openrouter-profile", "6"): old_profile,
        }[(identity, revision)]
        store.list_provider_bindings.return_value = [
            SimpleNamespace(binding_id="openrouter-credential", status="active")
        ]
        store.list_capability_certificates.return_value = [
            SimpleNamespace(
                certificate_id="old-openrouter-certificate",
                model_provider_id="openrouter",
            ),
            SimpleNamespace(
                certificate_id="codex-certificate",
                model_provider_id="codex",
            ),
        ]
        store.get_capability_certificate_status.return_value = (
            CapabilityCertificateStatus(
                certificate_id="old-openrouter-certificate",
                status="active",
                revision=0,
                updated_at=now,
            )
        )

        def save_binding(record, *, expected_revision):
            bindings[bindings.index(old_openrouter)] = record
            return record

        store.save_workspace_agentic_profile_binding.side_effect = save_binding
        state = SimpleNamespace(
            provider_store=store,
            provider_registry=MagicMock(),
            observability_store=MagicMock(),
            workspace_store=MagicMock(),
        )
        current = _binding(
            "current-openrouter",
            profile.definition_id,
            profile.revision,
            profile,
            now,
        )
        with patch(
            "core.providers.certification_openrouter_release."
            "ensure_openrouter_agentic_preview_profile",
            return_value=profile,
        ), patch(
            "core.providers.certification_openrouter_release."
            "publish_openrouter_preview_certificate",
            return_value=SimpleNamespace(certificate_id=profile.capability_certificate_id),
        ), patch(
            "core.providers.certification_openrouter_release.save_workspace_agentic_binding",
            return_value=current,
        ), patch(
            "core.providers.certification_openrouter_release.revoke_capability_certificate"
        ) as revoke:
            result = activate_certified_openrouter_release(
                state,
                signed_run=MagicMock(),
                trusted_keys={},
                now=now,
            )

        self.assertEqual(result["preserved_default_binding_id"], codex.binding_id)
        self.assertFalse(result["binding_is_default"])
        self.assertEqual(result["disabled_binding_ids"], [old_openrouter.binding_id])
        self.assertFalse(bindings[1].enabled)
        revoke.assert_called_once()


def _binding(
    binding_id: str,
    definition_id: str,
    definition_revision: str,
    profile,
    now: datetime,
    *,
    is_default: bool = False,
) -> WorkspaceAgenticProfileBinding:
    return WorkspaceAgenticProfileBinding(
        binding_id=binding_id,
        workspace_id="default",
        definition_id=definition_id,
        definition_revision=definition_revision,
        credential_binding_id=None,
        enabled=True,
        is_default=is_default,
        actor_policy=MagicMock(),
        workspace_policy_ceiling=profile.policy_ceiling,
        egress_policy_id=profile.egress_policy_id,
        egress_policy_revision=profile.egress_policy_revision,
        revision=0,
        created_at=now,
        updated_at=now,
    )


if __name__ == "__main__":
    unittest.main()
