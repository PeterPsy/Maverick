from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.apps.surfaces import resolve_workspace_app_surface, workspace_app_surface_snapshot


class WorkspaceAppSurfaceCacheTestCase(unittest.TestCase):
    def test_request_snapshots_are_nested_and_discarded_after_failures(self) -> None:
        binding = SimpleNamespace(workspace_id="default", app_id="storage", source_kind="platform", source_record_id="source")
        store = SimpleNamespace(get_app_source=Mock(return_value=object()))
        versions = [(Path("/repo"), object()) for _ in range(3)]
        with patch("core.apps.surfaces.load_contract_from_source_record", side_effect=versions) as load:
            with workspace_app_surface_snapshot():
                first = resolve_workspace_app_surface(store, binding=binding)
                self.assertIs(resolve_workspace_app_surface(store, binding=binding), first)
                with self.assertRaises(ValueError), workspace_app_surface_snapshot():
                    self.assertIs(resolve_workspace_app_surface(store, binding=binding), versions[1])
                    raise ValueError("request interrupted")
                self.assertIs(resolve_workspace_app_surface(store, binding=binding), first)
            with workspace_app_surface_snapshot():
                self.assertIs(resolve_workspace_app_surface(store, binding=binding), versions[2])
        self.assertEqual(load.call_count, 3)

    def test_tick_local_cache_reuses_one_source_lookup_and_contract_parse(self) -> None:
        binding = SimpleNamespace(
            workspace_id="default",
            app_id="storage",
            source_kind="platform",
            source_record_id="source:storage",
        )
        source = object()
        store = SimpleNamespace(get_app_source=Mock(return_value=source))
        parsed = object()
        cache = {}

        with patch(
            "core.apps.surfaces.load_contract_from_source_record",
            return_value=(Path("/repo/apps/storage"), parsed),
        ) as load_contract:
            first = resolve_workspace_app_surface(store, binding=binding, surface_cache=cache)
            second = resolve_workspace_app_surface(store, binding=binding, surface_cache=cache)

        self.assertEqual(first, second)
        store.get_app_source.assert_called_once_with("source:storage")
        load_contract.assert_called_once_with(source, start_path=None)


if __name__ == "__main__":
    unittest.main()
