from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.providers.provider_codex import build_codex_definition
from core.runtime.service import create_runtime_session
from core.runtime.turn_submission_launch_cache import clear_cached_runtime_launch_context
from core.runtime.turn_submission_service_output import _build_launch_spec_for_execution
from tests.support.repo import make_temp_repo_root
from tests.unit.providers.test_turn_submission_launch_spec import _FakeRuntimeAdapter, _runtime_store


class StorageLaunchCacheTestCase(unittest.TestCase):
    def test_storage_skill_catalog_state_changes_do_not_invalidate_launch_context(self) -> None:
        repo_root = make_temp_repo_root(self)
        runtime_store = _runtime_store()
        storage_data_root = repo_root / "workspaces" / "default" / "data" / "storage"
        skill_root = storage_data_root / "skills" / "storage-ops"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "---\nname: storage-ops\ndescription: Use Storage.\n---\n\nUse Storage safely.\n",
            encoding="utf-8",
        )
        (storage_data_root / "state.json").write_text(
            json.dumps({"schema_version": "1", "view_mode": "grid"}) + "\n",
            encoding="utf-8",
        )
        session = create_runtime_session(
            runtime_store,
            session_id="sess-storage-cache",
            workspace_id="default",
            agent_id="agent-1",
            skill_catalog_app_id="storage",
            start_path=repo_root,
        )
        adapter = _FakeRuntimeAdapter()
        state = SimpleNamespace(
            provider_store=SimpleNamespace(),
            runtime_store=runtime_store,
            secret_store=None,
            observability_store=None,
            repository_root=repo_root,
        )
        clear_cached_runtime_launch_context(session.session_id)

        first_spec, first_metadata = _build_launch_spec_for_execution(
            state,
            session=session,
            provider_id="codex",
            provider_definition=build_codex_definition(),
            provider_selection=None,
            runtime_adapter=adapter,
        )
        (storage_data_root / "state.json").write_text(
            json.dumps({"schema_version": "1", "view_mode": "list"}) + "\n",
            encoding="utf-8",
        )
        with patch("pathlib.Path.rglob", side_effect=AssertionError("launch fingerprint should not scan skill trees")):
            second_spec, second_metadata = _build_launch_spec_for_execution(
                state,
                session=session,
                provider_id="codex",
                provider_definition=build_codex_definition(),
                provider_selection=None,
                runtime_adapter=adapter,
            )

        self.assertIs(first_spec, second_spec)
        self.assertFalse(first_metadata["launch_cache_hit"])
        self.assertTrue(second_metadata["launch_cache_hit"])
        self.assertEqual(second_metadata["skill_count"], 1)
        self.assertEqual(adapter.launch_calls, [(None, None)])
        self.assertEqual(adapter.skill_prepare_calls, [["storage-ops"]])


if __name__ == "__main__":
    unittest.main()
