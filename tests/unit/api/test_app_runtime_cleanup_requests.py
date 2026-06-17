from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.api import app_runtime_cleanup_requests
from core.apps.errors import AppHostingError
from core.runtime.service import create_runtime_session
from core.runtime.store import RuntimeCollections, RuntimeDocumentStore
from tests.support.collections import FakeCollection
from tests.support.repo import make_temp_repo_root


class AppRuntimeCleanupRequestsTest(unittest.TestCase):
    def _runtime_store(self) -> RuntimeDocumentStore:
        return RuntimeDocumentStore(
            RuntimeCollections(
                sessions=FakeCollection(),
                turns=FakeCollection(),
                events=FakeCollection(),
                processes=FakeCollection(),
                states=FakeCollection(),
                threads=FakeCollection(),
            )
        )

    def test_cleanup_request_rejects_hidden_inter_agent_session(self) -> None:
        runtime_store = self._runtime_store()
        repo_root = make_temp_repo_root(self)
        create_runtime_session(
            runtime_store,
            session_id="hidden-child",
            workspace_id="default",
            agent_id="child-agent",
            source_app_id="video-studio",
            session_kind="inter_agent_participant",
            thread_visibility="hidden",
            start_path=repo_root,
        )
        state = SimpleNamespace(runtime_store=runtime_store)

        with self.assertRaisesRegex(AppHostingError, "hidden inter-agent runtime session"):
            app_runtime_cleanup_requests._runtime_cleanup_session_ids_for_request(
                state,
                workspace_id="default",
                app_id="video-studio",
                item={"runtime_session_id": "hidden-child"},
            )


if __name__ == "__main__":
    unittest.main()
