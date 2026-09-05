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
from core.providers.google_agentic_profile import (
    GOOGLE_AGENTIC_PROFILE_ID,
    GOOGLE_AGENTIC_PROFILE_REVISION,
)
from core.providers.agentic_profiles import resolve_workspace_agentic_profile
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class RuntimeRemoteDataDeclarationApiTest(AppReferenceApiTestSupport, unittest.TestCase):
    def test_partial_native_policy_is_rejected_without_rewriting_restrictions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state, app, cookie = self._platform(temp_dir)
            _definition, binding = resolve_workspace_agentic_profile(state.provider_store, workspace_id="default")
            restricted = replace(binding, workspace_policy_ceiling=replace(
                binding.workspace_policy_ceiling, tool_handle_mode="none",
                allow_filesystem_list=False, allow_filesystem_read=False,
                allow_filesystem_write=False, allow_shell=False,
            ), revision=binding.revision + 1)
            state.provider_store.save_workspace_agentic_profile_binding(restricted, expected_revision=binding.revision)
            with patch("core.api.runtime_api.create_runtime_session") as create, patch(
                "core.api.runtime_api.acquire_prepared_session"
            ) as prepare, patch.object(state.runtime_store, "claim_client_message_id") as claim:
                status, payload, _headers = self._invoke(
                    app, path="/api/runtime/sessions", method="POST", cookie=cookie,
                    body={"agent_id": "chat", "source_app_id": "chat", "runtime_mode": "agentic",
                          "input_text": "must not persist", "client_message_id": "partial-agent"},
                )
            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "full_workspace_policy_incomplete")
            create.assert_not_called()
            prepare.assert_not_called()
            claim.assert_not_called()
            self.assertEqual(state.provider_store.get_workspace_agentic_profile_binding(binding.binding_id), restricted)

    def test_removed_native_model_is_rejected_before_any_session_persistence(self) -> None:
        from core.providers.native_agent_reconciliation import refresh_codex_native_catalog
        from tests.support.native_agent_catalog import codex_snapshot

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.providers.native_agent_reconciliation.discover_codex_native_catalog",
            return_value=codex_snapshot("gpt-5.6-sol", "remaining-model"),
        ) as discovery:
            state, app, cookie = self._platform(temp_dir)
            discovery.return_value = codex_snapshot("remaining-model")
            refresh_codex_native_catalog(state.provider_registry, store=state.provider_store, force=True)
            before = state.runtime_store.list_all_sessions()
            with patch("core.api.runtime_api.create_runtime_session") as create, patch(
                "core.api.runtime_api.acquire_prepared_session"
            ) as prepare, patch.object(state.runtime_store, "claim_client_message_id") as claim:
                status, payload, _headers = self._invoke(
                    app, path="/api/runtime/sessions", method="POST", cookie=cookie,
                    body={"agent_id": "chat", "source_app_id": "chat", "runtime_mode": "agentic",
                          "input_text": "must not persist", "client_message_id": "removed-model-message"},
                )
            self.assertEqual(status, 409)
            self.assertEqual(payload["error"], "native_agent_model_unavailable")
            create.assert_not_called()
            prepare.assert_not_called()
            claim.assert_not_called()
            self.assertEqual(state.runtime_store.list_all_sessions(), before)

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
            self.assertEqual(pinned["workspace_binding_revision"], binding.revision)
            self.assertEqual(pinned["profile_definition_id"], definition.definition_id)
            self.assertEqual(
                pinned["profile_definition_revision"],
                definition.revision,
            )

    def test_profile_mutation_fails_before_claim_prepared_lock_or_runtime_records(self) -> None:
        request_shapes = {
            "claim": {
                "input_text": "must not persist",
                "client_message_id": "mutating-profile-message",
            },
            "prepared": {"prepare_only": True},
        }
        for mutation in ("revision", "default", "definition"):
            for request_kind, request_fields in request_shapes.items():
                with self.subTest(mutation=mutation, request_kind=request_kind), tempfile.TemporaryDirectory() as temp_dir:
                    state, app, cookie = self._platform(temp_dir)
                    resolver = self._mutating_profile_resolver(state, mutation=mutation)
                    before_sessions = state.runtime_store.list_all_sessions()
                    before_threads = state.runtime_store.list_threads("default")

                    with patch(
                        "core.api.runtime_api.resolve_workspace_agentic_profile",
                        side_effect=resolver,
                    ), patch.object(
                        state.runtime_store,
                        "claim_client_message_id",
                        wraps=state.runtime_store.claim_client_message_id,
                    ) as claim_client_message, patch(
                        "core.api.runtime_api.acquire_prepared_session",
                    ) as acquire_prepared, patch(
                        "core.api.runtime_api.create_runtime_session",
                    ) as create_session, patch(
                        "core.api.runtime_api.create_runtime_thread",
                    ) as create_thread, patch(
                        "core.api.runtime_api.submit_runtime_turn",
                    ) as submit_turn, patch(
                        "core.api.runtime_api.submit_runtime_turn_async",
                    ) as submit_turn_async:
                        status, payload, _headers = self._invoke(
                            app,
                            path="/api/runtime/sessions",
                            method="POST",
                            body={
                                "agent_id": "chat",
                                "source_app_id": "chat",
                                "runtime_mode": "agentic",
                                **request_fields,
                            },
                            cookie=cookie,
                        )

                    self.assertEqual(status, 409)
                    self.assertIn(
                        payload["error"],
                        {
                            "workspace_profile_binding_changed",
                            "profile_definition_invalid",
                        },
                    )
                    claim_client_message.assert_not_called()
                    acquire_prepared.assert_not_called()
                    create_session.assert_not_called()
                    create_thread.assert_not_called()
                    submit_turn.assert_not_called()
                    submit_turn_async.assert_not_called()
                    self.assertEqual(
                        state.runtime_store.list_all_sessions(),
                        before_sessions,
                    )
                    self.assertEqual(
                        state.runtime_store.list_threads("default"),
                        before_threads,
                    )

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
    def _mutating_profile_resolver(state, *, mutation: str):
        def resolve_then_mutate(*args, **kwargs):
            definition, binding = resolve_workspace_agentic_profile(*args, **kwargs)
            now = datetime.now(UTC)
            if mutation == "revision":
                state.provider_store.save_workspace_agentic_profile_binding(
                    replace(
                        binding,
                        revision=binding.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=binding.revision,
                )
            elif mutation == "default":
                state.provider_store.save_workspace_agentic_profile_binding(
                    replace(
                        binding,
                        is_default=False,
                        revision=binding.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=binding.revision,
                )
                state.provider_store.save_workspace_agentic_profile_binding(
                    replace(
                        binding,
                        binding_id="workspace-agentic-concurrent-default",
                        revision=0,
                        created_at=now,
                        updated_at=now,
                    ),
                    expected_revision=None,
                )
            elif mutation == "definition":
                status = state.provider_store.get_agentic_profile_definition_status(
                    definition.definition_id,
                    definition.revision,
                )
                state.provider_store.save_agentic_profile_definition_status(
                    replace(
                        status,
                        rollout_status="suspended",
                        revision=status.revision + 1,
                        updated_at=now,
                    ),
                    expected_revision=status.revision,
                )
            else:
                raise AssertionError(f"Unknown mutation {mutation}")
            return definition, binding

        return resolve_then_mutate

    @staticmethod
    def _remote_binding(state):
        definition = state.provider_store.get_agentic_profile_definition(
            GOOGLE_AGENTIC_PROFILE_ID,
            GOOGLE_AGENTIC_PROFILE_REVISION,
        )
        now = datetime.now(UTC)
        return state.provider_store.save_workspace_agentic_profile_binding(
            WorkspaceAgenticProfileBinding(
                binding_id="binding-google-contained-api",
                workspace_id="default",
                definition_id=definition.definition_id,
                definition_revision=definition.revision,
                credential_binding_id=None,
                enabled=True,
                is_default=False,
                actor_policy=default_actor_selection_policy(),
                workspace_policy_ceiling=definition.policy_ceiling,
                egress_policy_id=definition.egress_policy_id,
                egress_policy_revision=definition.egress_policy_revision,
                revision=0,
                created_at=now,
                updated_at=now,
            ),
            expected_revision=None,
        )


if __name__ == "__main__":
    unittest.main()
