"""Provider credential authorization preflight tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import unittest

from core.providers.models import ProviderCredentialBinding, ProviderCredentialRequirement
from core.providers.provider_authorization import (
    check_provider_credential_authorization,
    provider_secret_target,
)
from core.providers.provider_credentials import bind_provider_credential
from core.providers.provider_hosted_metadata import build_hosted_provider_definitions
from core.providers.store import ProviderCollections, ProviderDocumentStore
from core.secrets.service import (
    bind_provider_secret,
    build_secret_ref,
    create_platform_secret,
    grant_app_secret_use,
)
from core.secrets.store import SecretCollections, SecretDocumentStore
from tests.support.collections import FakeCollection


class ProviderAuthorizationTest(unittest.TestCase):
    def make_provider_store(self) -> ProviderDocumentStore:
        return ProviderDocumentStore(
            ProviderCollections(
                definitions=FakeCollection(),
                bindings=FakeCollection(),
                selections=FakeCollection(),
            )
        )

    def make_secret_store(self) -> SecretDocumentStore:
        return SecretDocumentStore(
            SecretCollections(
                secrets=FakeCollection(),
                values=FakeCollection(),
                bindings=FakeCollection(),
                grants=FakeCollection(),
            )
        )

    def groq_definition(self):
        definitions = build_hosted_provider_definitions(datetime(2026, 6, 22, 12, 0, tzinfo=UTC))
        return next(definition for definition in definitions if definition.provider_id == "groq")

    def test_missing_provider_binding_is_reported_without_secret_values(self) -> None:
        authorization = check_provider_credential_authorization(
            self.make_provider_store(),
            definition=self.groq_definition(),
            workspace_id="default",
        )

        self.assertTrue(authorization.required)
        self.assertFalse(authorization.authorized)
        self.assertEqual(authorization.secret_alias_or_logical_name, "groq_api_key")
        self.assertIn("provider_credential_binding_missing", authorization.reason_codes)
        self.assertFalse(hasattr(authorization, "secret_ref"))

    def test_provider_credential_binding_authorizes_without_exposing_secret_ref(self) -> None:
        provider_store = self.make_provider_store()
        binding = bind_provider_credential(
            provider_store,
            provider_id="groq",
            workspace_id="default",
            secret_ref="platform:secret-alias/groq",
            label="Groq API key",
        )

        authorization = check_provider_credential_authorization(
            provider_store,
            definition=self.groq_definition(),
            workspace_id="default",
        )

        self.assertTrue(authorization.authorized)
        self.assertEqual(authorization.provider_credential_binding_id_optional, binding.binding_id)
        self.assertIn("provider_credential_binding_present", authorization.reason_codes)
        self.assertNotIn("platform:secret-alias/groq", str(authorization))

    def test_legacy_provider_credential_binding_does_not_authorize(self) -> None:
        provider_store = self.make_provider_store()
        now = datetime(2026, 6, 22, 12, 0, tzinfo=UTC)
        provider_store.save_provider_binding(
            ProviderCredentialBinding(
                binding_id="legacy-groq",
                provider_id="groq",
                workspace_id="default",
                secret_ref="platform:providers/groq",
                label="Legacy Groq",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

        authorization = check_provider_credential_authorization(
            provider_store,
            definition=self.groq_definition(),
            workspace_id="default",
        )

        self.assertFalse(authorization.authorized)
        self.assertIn("provider_credential_binding_invalid_secret_ref", authorization.reason_codes)
        self.assertNotIn("platform:providers/groq", str(authorization))

    def test_provider_secret_binding_authorizes_without_reading_secret_value(self) -> None:
        secret_store = self.make_secret_store()
        secret = create_platform_secret(
            secret_store,
            label="Groq",
            raw_value="super-secret-token",
            alias="groq-key",
            kind="api_key",
        )
        binding = bind_provider_secret(
            secret_store,
            provider_id="groq",
            workspace_id="default",
            logical_name="groq_api_key",
            secret_ref=build_secret_ref(secret_id=secret.secret_id),
        )

        authorization = check_provider_credential_authorization(
            self.make_provider_store(),
            definition=self.groq_definition(),
            workspace_id="default",
            secret_store=secret_store,
        )

        self.assertTrue(authorization.authorized)
        self.assertEqual(authorization.provider_secret_binding_id_optional, binding.binding_id)
        self.assertIn("provider_secret_binding_present", authorization.reason_codes)
        self.assertNotIn("super-secret-token", str(authorization))
        self.assertNotIn(build_secret_ref(secret_id=secret.secret_id), str(authorization))

    def test_app_secret_grant_authorizes_only_app_scope(self) -> None:
        secret_store = self.make_secret_store()
        secret = create_platform_secret(
            secret_store,
            label="Groq App",
            raw_value="app-secret-token",
            alias="groq-app-key",
            kind="api_key",
        )
        grant = grant_app_secret_use(
            secret_store,
            workspace_id="default",
            app_id="chat",
            logical_name="groq_api_key",
            secret_ref=build_secret_ref(secret_id=secret.secret_id),
            actions=["provider.hosted_text.execute"],
            target_patterns=[provider_secret_target("groq", "plain_hosted_chat")],
        )
        app_definition = replace(
            self.groq_definition(),
            credential_requirements=[
                ProviderCredentialRequirement(
                    secret_alias_or_logical_name="groq_api_key",
                    secret_kind="api_key",
                    required_for_modes=["plain_hosted_chat"],
                    secret_binding_scope="app",
                )
            ],
        )

        authorization = check_provider_credential_authorization(
            self.make_provider_store(),
            definition=app_definition,
            workspace_id="default",
            secret_store=secret_store,
            app_id="chat",
            target=provider_secret_target("groq", "plain_hosted_chat"),
        )

        self.assertTrue(authorization.authorized)
        self.assertEqual(authorization.app_secret_grant_id_optional, grant.grant_id)
        self.assertIn("app_secret_grant_present", authorization.reason_codes)
        self.assertNotIn("app-secret-token", str(authorization))


if __name__ == "__main__":
    unittest.main()
