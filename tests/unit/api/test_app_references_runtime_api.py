from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.apps.service import install_store_app, register_app_source_from_contract
from core.runtime.runtime_turns import RuntimeTurnRecord
from core.runtime.service import create_runtime_session
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class AppReferencesRuntimeApiTestCase(AppReferenceApiTestSupport, unittest.TestCase):
    def test_runtime_turn_materializes_references_server_side(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = self._repo_root(temp_dir)
            self._write_reference_app(repo_root / "apps" / "records")
            with patch.dict(
                "os.environ",
                {
                    "MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1",
                    "MAVERICK_ADMIN_USERNAME": "admin",
                    "MAVERICK_ADMIN_PASSWORD": "maverick",
                },
            ):
                state = bootstrap_platform_state(start_path=repo_root)
            source = register_app_source_from_contract(
                state.app_store,
                source_kind="platform",
                source_path=str(repo_root / "apps" / "records"),
            )
            install_store_app(state.app_store, source_id=source.source_id, workspace_id="default", start_path=repo_root)
            session = create_runtime_session(
                state.runtime_store,
                session_id="sess-1",
                workspace_id="default",
                agent_id="chat",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)
            captured: dict[str, object] = {}

            def fake_submit_runtime_turn(*_args, **kwargs):
                captured["app_references"] = kwargs.get("app_references")
                materializer = kwargs.get("app_reference_materializer")
                if callable(materializer):
                    captured["materialized_app_references"] = materializer(kwargs.get("app_references") or [])
                now = datetime.now(timezone.utc)
                return RuntimeTurnRecord(
                    turn_id="turn-1",
                    session_id=session.session_id,
                    workspace_id=session.workspace_id,
                    status="queued",
                    input_text=kwargs["input_text"],
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    completed_at=None,
                    failure_reason=None,
                ), []

            with patch("core.api.runtime_api.submit_runtime_turn_async", side_effect=fake_submit_runtime_turn):
                status, _payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions/sess-1/turns",
                    method="POST",
                    body={
                        "input_text": "Review @Launch record [ref:records/record/record-1]",
                        "async": True,
                        "app_references": [
                            {
                                "type": "entity",
                                "app_id": "records",
                                "entity_type": "record",
                                "entity_id": "record-1",
                                "label": "Forged label",
                                "summary": "Forged summary",
                                "deep_link": "/app/records/private",
                            },
                            {
                                "type": "entity",
                                "app_id": "records",
                                "entity_type": "record",
                                "entity_id": "deleted",
                                "label": "Deleted but forged",
                                "summary": "Forged deleted summary",
                                "deep_link": "/app/records/private-deleted",
                            },
                        ],
                    },
                    cookie=cookie,
                )

        self.assertEqual(status, 202)
        self.assertEqual(
            captured["app_references"],
            [
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "record-1",
                    "label": "record-1",
                    "summary": "",
                },
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "deleted",
                    "label": "deleted",
                    "summary": "",
                },
            ],
        )
        self.assertEqual(
            captured["materialized_app_references"],
            [
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "record-1",
                    "label": "Launch record",
                    "summary": "Safe summary",
                    "deep_link": "/app/records/records/record-1",
                },
                {
                    "type": "entity",
                    "app_id": "records",
                    "entity_type": "record",
                    "entity_id": "deleted",
                    "label": "deleted",
                    "summary": "",
                    "exists": False,
                },
            ],
        )

    def test_runtime_turn_rejects_empty_input_before_materializing_references(self) -> None:
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
            create_runtime_session(
                state.runtime_store,
                session_id="sess-1",
                workspace_id="default",
                agent_id="chat",
                start_path=repo_root,
            )
            app = PlatformHost(state, start_path=repo_root)
            cookie = self._login(app)

            with patch("core.api.runtime_api.materialize_runtime_app_references") as materialize:
                status, payload, _headers = self._invoke(
                    app,
                    path="/api/runtime/sessions/sess-1/turns",
                    method="POST",
                    body={
                        "input_text": "",
                        "app_references": [
                            {
                                "type": "entity",
                                "app_id": "records",
                                "entity_type": "record",
                                "entity_id": "record-1",
                            }
                        ],
                    },
                    cookie=cookie,
                )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "empty_runtime_input"})
        materialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
