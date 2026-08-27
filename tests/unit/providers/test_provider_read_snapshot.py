from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.api.provider_api import RuntimeSessionGovernanceProjectionContext
from core.providers.read_snapshot import ProviderReadSnapshot


class ProviderReadSnapshotTestCase(unittest.TestCase):
    def test_reuses_records_and_binding_queries_within_one_snapshot(self) -> None:
        certificate = object()
        bindings = [object()]
        store = Mock()
        store.get_capability_certificate.return_value = certificate
        store.list_provider_bindings.return_value = bindings
        snapshot = ProviderReadSnapshot(store)

        self.assertIs(snapshot.get_capability_certificate("certificate-1"), certificate)
        self.assertIs(snapshot.get_capability_certificate("certificate-1"), certificate)
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

        store.get_capability_certificate.assert_called_once_with("certificate-1")
        store.list_provider_bindings.assert_called_once_with(
            workspace_id="default",
            provider_id="codex",
        )

    def test_projection_context_hashes_each_adapter_once(self) -> None:
        context = RuntimeSessionGovernanceProjectionContext(
            provider_store=Mock(),
            registry=Mock(),
        )
        first_adapter = object()
        second_adapter = object()

        with patch(
            "core.api.provider_api.runtime_adapter_artifact_digest",
            side_effect=["first-digest", "second-digest"],
        ) as artifact_digest:
            self.assertEqual(
                context.adapter_artifact_digest(first_adapter),
                "first-digest",
            )
            self.assertEqual(
                context.adapter_artifact_digest(first_adapter),
                "first-digest",
            )
            self.assertEqual(
                context.adapter_artifact_digest(second_adapter),
                "second-digest",
            )

        self.assertEqual(artifact_digest.call_count, 2)


if __name__ == "__main__":
    unittest.main()
