"""Split tests from observability helper module."""

from __future__ import annotations

import json

from core.providers.agentic_models import codex_routing_constraint, codex_runtime_policy
from core.providers.certificate_service import runtime_adapter_artifact_digest
from core.runtime.execution_binding import build_runtime_execution_binding
from tests.support.observability import *


class TestCoreFlowObservability(ObservabilityTestBase):
    """Focused test slice."""

    def test_real_core_flows_emit_audit_and_event_records(self) -> None:
        class CredentialedAdapter:
            def provider_definition(self) -> ProviderDefinition:
                timestamp = datetime.now(tz=UTC)
                return ProviderDefinition(
                    provider_id="credentialed",
                    label="Credentialed",
                    description="Credentialed provider.",
                    kind="runtime_backend",
                    status="active",
                    capabilities=ProviderCapabilitySet(
                        supports_interactive_runtime=True,
                        supports_streaming=True,
                        supports_tools=True,
                        supports_mcp=False,
                        supports_skills=False,
                        supports_filesystem_access=True,
                        supports_remote_execution=False,
                        supports_api_key_auth=True,
                        supports_local_binary=True,
                    ),
                    default_model_family="credentialed",
                    requires_credentials=True,
                    supported_execution_modes=["sandbox"],
                    created_at=timestamp,
                    updated_at=timestamp,
                )

            def validate_backend(self) -> None:
                return None

            def build_launch_spec(self, session, *, secret_env=None, credential_binding_id=None, resolved_secret_refs=None) -> RuntimeBackendLaunchSpec:
                return RuntimeBackendLaunchSpec(
                    provider_id="credentialed",
                    command=["echo"],
                    env_overrides=dict(secret_env or {}),
                    credential_binding_id=credential_binding_id,
                    resolved_secret_refs=list(resolved_secret_refs or []),
                    working_directory=session.workdir,
                    execution_mode=session.effective_mode,
                    readable_roots=[session.workspace_root],
                    writable_roots=[session.workspace_root],
                )

            def prepare_runtime_skills(self, session, skills):
                return []

        repo_root = self.make_repo_root()
        observability_store = self.make_observability_store()
        app_store = self.make_app_store()
        provider_store = self.make_provider_store()
        secret_store = self.make_secret_store()
        runtime_store = self.make_runtime_store()
        workspace_store = self.make_workspace_store()
        ensure_default_workspace_record(workspace_store)
        registry = ProviderRegistry()
        registry.register_runtime_adapter(CredentialedAdapter())

        app_root = repo_root / "apps" / "audit-app"
        app_root.mkdir(parents=True, exist_ok=True)
        parsed = build_parsed_app_contract(
            app_id="audit-app",
            name="Audit App",
            version="1.0.0",
            description="Audit app",
            publisher="maverick",
            contract=build_app_contract(capabilities=build_app_capabilities()),
        )
        write_app_contract_file(app_root, parsed)
        source = register_app_source_from_contract(app_store, source_kind="platform", source_path=str(app_root))
        install_store_app(
            app_store,
            source_id=source.source_id,
            workspace_id="default",
            start_path=repo_root,
            observability_store=observability_store,
        )

        create_platform_secret(secret_store, label="Provider", raw_value="provider-secret", alias="provider-secret")
        bind_provider_credential(
            provider_store,
            provider_id="credentialed",
            secret_ref="platform:secret-alias/provider-secret",
            workspace_id="default",
            observability_store=observability_store,
        )
        selection = configure_workspace_provider(
            provider_store,
            workspace_id="default",
            provider_id="credentialed",
            registry=registry,
            observability_store=observability_store,
        )
        bridge = registry.get_agentic_runtime_adapter("credentialed")
        policy = codex_runtime_policy()
        execution_binding = build_runtime_execution_binding(
            session_id="sess-observed",
            workspace_id="default",
            profile_definition_id="profile-credentialed-observability",
            profile_definition_revision="1",
            workspace_binding_id="workspace-credentialed-observability",
            workspace_binding_revision=0,
            capability_certificate_id="certificate-credentialed-observability",
            certificate_evidence_digest="a" * 64,
            runtime_engine_id="credentialed",
            adapter_id=bridge.adapter_id,
            adapter_version=bridge.adapter_version,
            adapter_artifact_digest=runtime_adapter_artifact_digest(bridge),
            model_provider_id="credentialed",
            model_id="credentialed",
            provider_protocol="legacy-runtime-backend",
            provider_api_version=None,
            routing_constraint=codex_routing_constraint(),
            credential_binding_id=selection.binding_id,
            reasoning_effort=None,
            certified_reasoning_efforts=(),
            default_reasoning_effort=None,
            execution_mode="sandbox",
            profile_policy_ceiling=policy,
            workspace_policy_ceiling=policy,
            egress_policy_id="local-runtime-no-remote-egress",
            egress_policy_revision="1",
            created_at=datetime.now(tz=UTC),
        )

        session = create_runtime_session(
            runtime_store,
            session_id="sess-observed",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
            observability_store=observability_store,
            execution_binding=execution_binding,
        )
        transition_runtime_session(
            runtime_store,
            session_id=session.session_id,
            target_status="running",
            observability_store=observability_store,
            start_path=repo_root,
        )
        build_runtime_backend_launch_spec(
            provider_store,
            session=runtime_store.get_session(session.session_id),
            registry=registry,
            secret_store=secret_store,
            observability_store=observability_store,
        )
        record_failed_start(
            store=self.make_recovery_store(),
            category="missing_secret",
            detail="missing secret",
            workspace_id="default",
            session_id=session.session_id,
            observability_store=observability_store,
        )

        audit_actions = {item.action for item in observability_store.list_audit(workspace_id="default")}
        event_types = {item.event_type for item in observability_store.list_events(workspace_id="default")}
        self.assertIn("app.install.store", audit_actions)
        self.assertIn("provider.binding.create", audit_actions)
        self.assertIn("provider.selection.configure", audit_actions)
        self.assertIn("provider.launch_spec.build", audit_actions)
        self.assertIn("runtime.session.create", audit_actions)
        self.assertIn("app.installed", event_types)
        self.assertIn("runtime.session.created", event_types)
        self.assertIn("provider.launch_spec.built", event_types)
        launch_audit = next(item for item in observability_store.list_audit(workspace_id="default") if item.action == "provider.launch_spec.build")
        launch_event = next(item for item in observability_store.list_events(workspace_id="default") if item.event_type == "provider.launch_spec.built")
        for payload in (launch_audit.payload, launch_event.payload):
            self.assertNotIn("resolved_secret_refs", payload)
            self.assertEqual(payload["resolved_secret_ref_count"], 1)
            self.assertNotIn("platform:secret-alias/provider-secret", json.dumps(payload))
