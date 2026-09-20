from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.providers.agentic_models import (
    WorkspaceAgenticProfileBinding,
    default_actor_selection_policy,
)
from core.providers.google_agentic_profile import google_agentic_preview_publication
from core.providers.agentic_profiles import resolve_workspace_agentic_profile
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeRemoteDataDeclarationApiTest(AppReferenceApiTestSupport, unittest.TestCase):
    def test_restricted_native_policy_remains_selectable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            _definition, binding = resolve_workspace_agentic_profile(
                state.provider_store,
                workspace_id="default",
            )
            restricted = replace(
                binding,
                workspace_policy_ceiling=replace(
                    binding.workspace_policy_ceiling,
                    tool_handle_mode="none",
                    allow_filesystem_list=False,
                    allow_filesystem_read=False,
                    allow_filesystem_write=False,
                    allow_shell=False,
                ),
                updated_at=datetime.now(tz=UTC),
            )
            state.provider_store.save_workspace_agentic_profile_binding(restricted)

            with patch("core.api.runtime_api._prewarm_new_runtime_session", return_value=None):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    cookie=cookie,
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                    },
                )

            self.assertEqual(status, 201)
            self.assertEqual(
                payload["execution_binding"]["workspace_binding_id"],
                restricted.binding_id,
            )
            self.assertEqual(
                state.provider_store.get_workspace_agentic_profile_binding(binding.binding_id),
                restricted,
            )

    def test_catalog_refresh_does_not_disable_an_existing_model_config(self) -> None:
        from core.providers.native_agent_reconciliation import refresh_codex_native_catalog
        from tests.support.native_agent_catalog import codex_snapshot

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=codex_snapshot("gpt-5.6-sol", "remaining-model"),
        ) as discovery:
            state, app, cookie = self._platform(temp_dir)
            discovery.return_value = codex_snapshot("remaining-model")
            refresh_codex_native_catalog(state.provider_registry, store=state.provider_store, force=True)
            with patch("core.api.runtime_api._prewarm_new_runtime_session", return_value=None):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    cookie=cookie,
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                    },
                )
            self.assertEqual(status, 201)
            self.assertEqual(payload["execution_binding"]["model_id"], "gpt-5.6-sol")

    def test_authorized_codex_pin_matches_the_preflight_profile_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            definition, binding = resolve_workspace_agentic_profile(
                state.provider_store,
                workspace_id="default",
                enforce_remote_admission=False,
            )

            with patch(
                "core.api.runtime_api._prewarm_new_runtime_session",
                return_value=None,
            ):
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                    },
                    cookie=cookie,
                )

            self.assertEqual(status, 201)
            pinned = payload["execution_binding"]
            self.assertEqual(pinned["workspace_binding_id"], binding.binding_id)
            self.assertEqual(pinned["runtime_engine_id"], definition.runtime_engine_id)
            self.assertEqual(pinned["adapter_id"], definition.adapter_id)
            self.assertEqual(pinned["model_provider_id"], definition.model_provider_id)
            self.assertEqual(pinned["model_id"], definition.model_id)
            self.assertNotIn("profile_definition_id", pinned)
            self.assertNotIn("workspace_binding_revision", pinned)

    def test_remote_agentic_session_is_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            binding = self._remote_binding(state)
            before = state.runtime_store.list_all_sessions()

            with patch.object(
                state.runtime_store,
                "claim_client_message_id",
                wraps=state.runtime_store.claim_client_message_id,
            ) as claim_client_message:
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                        "workspace_profile_binding_id": binding.binding_id,
                        "input_text": "must never persist",
                        "client_message_id": "remote-client-message",
                    },
                    cookie=cookie,
                )

            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "hosted_agent_runtime_disabled")
            self.assertEqual(state.runtime_store.list_all_sessions(), before)
            claim_client_message.assert_not_called()

    def test_client_fake_declaration_is_not_synthesized_or_accepted(self) -> None:
        for declaration in (
            "workspace_internal_fake",
            {"data_class": "workspace_internal_fake"},
        ):
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as temp_dir:
                state, app, cookie = self._platform(temp_dir)
                binding = self._remote_binding(state)

                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                        "workspace_profile_binding_id": binding.binding_id,
                        "declared_remote_data_class": declaration,
                    },
                    cookie=cookie,
                )

                self.assertEqual(status, 409)
                self.assertEqual(
                    payload["error"],
                    "remote_data_declaration_not_accepted",
                )
                self.assertEqual(state.runtime_store.list_all_sessions(), [])

    def test_client_policy_attestation_and_classification_fields_are_rejected(self) -> None:
        cases = (
            {"data_class": "workspace_internal_fake"},
            {"egress_policy_id": "fake-data"},
            {"attestation_id": "browser-forged-attestation"},
            {
                "attachments": [
                    {
                        "content_type": "image/png",
                        "data_class": "public",
                    }
                ]
            },
        )
        for index, authority_fields in enumerate(cases):
            with self.subTest(authority_fields=authority_fields), tempfile.TemporaryDirectory() as temp_dir:
                state, app, cookie = self._platform(temp_dir)
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                        "client_message_id": f"client-authority-{index}",
                        **authority_fields,
                    },
                    cookie=cookie,
                )

                self.assertEqual(status, 409)
                self.assertEqual(
                    payload["error"],
                    "runtime_client_authority_not_accepted",
                )
                self.assertEqual(state.runtime_store.list_all_sessions(), [])

    def test_plain_hosted_session_rejects_agentic_remote_data_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            status, payload, _headers = self._invoke(
                app,
                path="/api/runtime/sessions",
                method="POST",
                body={
                    "agent_id": "chat",
                    "source_app_id": "chat",
                    "runtime_mode": "plain_hosted_chat",
                    "declared_remote_data_class": "workspace_internal_fake",
                },
                cookie=cookie,
            )

            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "remote_data_declaration_not_accepted")

    def test_existing_turn_rejects_client_classification_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            with patch(
                "core.api.runtime_api._prewarm_new_runtime_session",
                return_value=None,
            ):
                create_status, created, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions",
                    method="POST",
                    body={
                        "agent_id": "chat",
                        "source_app_id": "chat",
                        "runtime_mode": "agentic",
                    },
                    cookie=cookie,
                )
            self.assertEqual(create_status, 201)
            session_id = created["session_id"]
            before = state.runtime_store.list_turns(session_id)

            status, payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{session_id}/turns",
                method="POST",
                body={
                    "input_text": "must not persist",
                    "declared_remote_data_class": "workspace_internal_fake",
                },
                cookie=cookie,
            )

            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "remote_data_declaration_not_accepted")
            self.assertEqual(state.runtime_store.list_turns(session_id), before)

            status, payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{session_id}/turns",
                method="POST",
                body={
                    "input_text": "must not persist either",
                    "egress_policy_id": "browser-selected-policy",
                },
                cookie=cookie,
            )
            self.assertEqual(status, 400)
            self.assertEqual(
                payload["error"],
                "runtime_client_authority_not_accepted",
            )
            self.assertEqual(state.runtime_store.list_turns(session_id), before)

    def _platform(self, temp_dir: str):
        repo_root = self._repo_root(temp_dir)
        with patch.dict(
            "os.environ",
            {
                "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                "MAVERICK_ADMIN_USERNAME": "admin",
                "MAVERICK_ADMIN_PASSWORD": "maverick",
            },
        ):
            state = bootstrap_platform_state(start_path=repo_root)
        app = PlatformHost(state, start_path=repo_root)
        return state, app, self._login(app)

    @staticmethod
    def _remote_binding(state):
        # Exercise a contained historical profile without republishing it in
        # the production catalog, where Google API agents are retired.
        definition = state.provider_store.save_agentic_profile_definition(
            google_agentic_preview_publication().profile,
        )
        now = datetime.now(UTC)
        return state.provider_store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="binding-google-contained-api",
                workspace_id="default",
                definition_id=definition.definition_id,
                credential_binding_id=None,
                enabled=True,
                is_default=False,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=definition.policy_ceiling,
                egress_policy_id=definition.egress_policy_id,
                egress_policy_revision=definition.egress_policy_revision,
                created_at=now,
                updated_at=now,
            ),
        )


if __name__ == "__main__":
    unittest.main()
