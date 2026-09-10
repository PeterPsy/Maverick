"""The natural-conformance laboratory is signed, bounded, and opt-in."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.providers.certification_natural_lab import (
    CertificationNaturalLabPermit,
    CertificationNaturalLabAuthority,
    build_certification_natural_runtime_registry,
    directory_identity,
    sign_certification_natural_lab_permit,
    verify_certification_natural_lab_permit,
)
from core.api.platform_state import bootstrap_platform_state
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.providers.errors import CapabilityCertificateError
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PROFILE_REVISION,
)
from core.providers.provider_registry import ProviderRegistry
from core.runtime.hosted_agentic_factory import build_hosted_agentic_engine_adapter
from tests.support.repo import make_temp_repo_root


class CertificationNaturalLabPermitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.now = datetime.now(tz=UTC)

    def test_signed_exact_permit_verifies_and_tampering_fails(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            os.chmod(root, 0o700)
            workspace = root / "workspace"
            workspace.mkdir(mode=0o700)
            permit = self._permit(root, workspace)
            signed = sign_certification_natural_lab_permit(
                permit,
                signer_key_id="p6-local",
                private_key=self.key,
            )
            self.assertEqual(
                verify_certification_natural_lab_permit(
                    signed,
                    trusted_keys={"p6-local": self.key.public_key()},
                    now=self.now + timedelta(seconds=1),
                ),
                permit,
            )
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_lab_signature_invalid",
            ):
                verify_certification_natural_lab_permit(
                    replace(
                        signed,
                        permit=replace(permit, reasoning_effort="other"),
                    ),
                    trusted_keys={"p6-local": self.key.public_key()},
                    now=self.now + timedelta(seconds=1),
                )

    def test_untrusted_expired_or_unbounded_permit_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            permit = self._permit(root, workspace)
            signed = sign_certification_natural_lab_permit(
                permit,
                signer_key_id="p6-local",
                private_key=self.key,
            )
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_lab_signer_untrusted",
            ):
                verify_certification_natural_lab_permit(
                    signed,
                    trusted_keys={},
                    now=self.now + timedelta(seconds=1),
                )
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_lab_permit_invalid",
            ):
                verify_certification_natural_lab_permit(
                    signed,
                    trusted_keys={"p6-local": self.key.public_key()},
                    now=permit.expires_at,
                )
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_lab_permit_invalid",
            ):
                sign_certification_natural_lab_permit(
                    replace(
                        permit,
                        expires_at=permit.issued_at + timedelta(days=2),
                    ),
                    signer_key_id="p6-local",
                    private_key=self.key,
                )

    def test_directory_identity_rejects_symlinks(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            self.assertEqual(len(directory_identity(target)), 64)
            with self.assertRaisesRegex(
                CapabilityCertificateError,
                "certification_lab_path_invalid",
            ):
                directory_identity(link)

    def test_lab_transport_keeps_the_exact_production_adapter_artifact(self) -> None:
        root = make_temp_repo_root(self)
        with patch.dict(
            os.environ,
            {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
            clear=False,
        ):
            state = bootstrap_platform_state(
                start_path=root,
                now=self.now,
                install_builtin_apps=False,
            )
        production_registry = ProviderRegistry()
        production_registry.register_provider_definition(
            state.provider_registry.get_provider_definition("maverick-tool-loop")
        )
        production = build_hosted_agentic_engine_adapter(
            state,
            provider_registry=production_registry,
            onboarding_catalog=state.maverick_agent_onboarding_catalog,
        )
        authority = object.__new__(CertificationNaturalLabAuthority)
        authority.state = state
        authority.permit = SimpleNamespace(
            definition_id=GOOGLE_AGENTIC_PROFILE_ID,
            definition_revision=GOOGLE_AGENTIC_PROFILE_REVISION,
        )
        bound = []
        authority.bind_adapter = bound.append
        laboratory_registry = ProviderRegistry()
        laboratory_registry.register_provider_definition(
            state.provider_registry.get_provider_definition("maverick-tool-loop")
        )
        laboratory = build_hosted_agentic_engine_adapter(
            state,
            provider_registry=laboratory_registry,
            onboarding_catalog=state.maverick_agent_onboarding_catalog,
            certification_lab_authority=authority,
            certification_lab_runtime_registry=(
                build_certification_natural_runtime_registry(authority)
            ),
        )
        self.assertEqual(bound, [laboratory])
        self.assertEqual(
            runtime_adapter_artifact_digest(laboratory),
            runtime_adapter_artifact_digest(production),
        )

    def _permit(self, root: Path, workspace: Path) -> CertificationNaturalLabPermit:
        return CertificationNaturalLabPermit(
            schema="maverick-certification-natural-lab-permit.v1",
            permit_id="permit-1",
            authorization_ref="a" * 64,
            source_commit="b" * 40,
            repository_root_identity=directory_identity(root),
            target_digest="c" * 64,
            adapter_artifact_digest="d" * 64,
            tcb_manifest_id="tcb",
            tcb_manifest_version="1",
            tcb_structure_digest="e" * 64,
            tcb_live_digest="f" * 64,
            workspace_id="workspace",
            workspace_root=str(workspace),
            workspace_root_identity=directory_identity(workspace),
            actor_user_id="actor",
            definition_id="definition",
            definition_revision="1",
            workspace_binding_id="binding",
            credential_binding_digest="1" * 64,
            reasoning_effort="high",
            ledger_policy_digest="2" * 64,
            run_id="natural-run",
            reviewer_ref="3" * 64,
            issued_at=self.now,
            expires_at=self.now + timedelta(hours=1),
        )


if __name__ == "__main__":
    unittest.main()
