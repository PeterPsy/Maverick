"""Split tests from tests/test_phase11_observability.py."""

from __future__ import annotations

from tests.phase11_observability_helpers import *


class TestPhase11CoreFlowObservability(Phase11ObservabilityBase):
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
        configure_workspace_provider(
            provider_store,
            workspace_id="default",
            provider_id="credentialed",
            registry=registry,
            observability_store=observability_store,
        )

        session = create_runtime_session(
            runtime_store,
            session_id="sess-observed",
            workspace_id="default",
            agent_id="agent-1",
            start_path=repo_root,
            observability_store=observability_store,
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
