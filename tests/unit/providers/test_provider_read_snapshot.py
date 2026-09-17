from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.api.provider_api import ProviderProjectionContext
from core.providers.read_snapshot import ProviderReadSnapshot


class ProviderReadSnapshotTestCase(unittest.TestCase):
    def test_reuses_records_and_binding_queries_within_one_snapshot(self) -> None:
        profile = object()
        profiles = [profile]
        bindings = [object()]
        store = Mock()
        store.get_agentic_profile_definition.return_value = profile
        store.list_agentic_profile_definitions.return_value = profiles
        store.list_provider_bindings.return_value = bindings
        snapshot = ProviderReadSnapshot(store)

        self.assertIs(
            snapshot.get_agentic_profile_definition("profile-1"),
            profile,
        )
        self.assertIs(
            snapshot.get_agentic_profile_definition("profile-1"),
            profile,
        )
        self.assertIs(snapshot.list_agentic_profile_definitions(), profiles)
        self.assertIs(snapshot.list_agentic_profile_definitions(), profiles)
        self.assertIs(
            snapshot.list_provider_bindings(
                workspace_id="default",
                provider_id="codex",
            ),
            bindings,
        )
        self.assertIs(
            snapshot.list_provider_bindings(
                workspace_id="default",
                provider_id="codex",
            ),
            bindings,
        )

        store.get_agentic_profile_definition.assert_called_once_with("profile-1")
        store.list_agentic_profile_definitions.assert_called_once_with()
        store.list_provider_bindings.assert_called_once_with(
            workspace_id="default",
            provider_id="codex",
        )

    def test_projection_context_inspects_native_runtimes_once(self) -> None:
        provider_store = Mock()
        registry = Mock()
        context = ProviderProjectionContext(
            provider_store=provider_store,
            registry=registry,
        )
        native_items = [{"runtime_engine_id": "codex"}]

        with patch(
            "core.api.provider_api.native_agent_status_items",
            return_value=native_items,
        ) as inspect_native:
            self.assertIs(context.native_items(), native_items)
            self.assertIs(context.native_items(), native_items)

        inspect_native.assert_called_once_with(registry, store=provider_store)


if __name__ == "__main__":
    unittest.main()
