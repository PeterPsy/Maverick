"""Certified rollout and HTTP admission regressions for Codex continuations."""

from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import os
import sqlite3
import unittest
from unittest.mock import patch

from core.api.platform_host import PlatformHost
from core.api.platform_state import bootstrap_platform_state
from core.providers.errors import CapabilityCertificateError
from core.recovery.continuation_rollout import (
    repair_runtime_continuations_after_certified_rollout,
)
from core.runtime.errors import RuntimeThreadNotFoundError
from core.runtime.turn_submission import RuntimeSessionPrewarmResult
from core.runtime.turn_submission_service_queue import _queue_turn_with_event
from tests.support.continuation import NOW, RuntimeContinuationFixture
from tests.support.native_continuation import NativeContinuationIdentityFixture
from tests.unit.api.app_reference_test_support import AppReferenceApiTestSupport


class CertifiedContinuationRolloutTest(
    RuntimeContinuationFixture,
    NativeContinuationIdentityFixture,
    AppReferenceApiTestSupport,
    unittest.TestCase,
):
    def test_rollout_ignores_empty_prepared_session_and_upgrades_visible_chat(self):
        historical_projection, _historical_root, installation, codex = (
            self._install_historical_projection()
        )
        source = self._source_session(
            "automatic-visible-history",
            target_workspace_binding_id=codex.binding_id,
            source_certificate=historical_projection,
        )
        prepared = self._source_session(
            "automatic-empty-prepared",
            target_workspace_binding_id=codex.binding_id,
            source_certificate=historical_projection,
        )
        prepared = self.state.runtime_store.save_session(
            replace(
                prepared,
                thread_visibility="hidden",
                prepared_session_fingerprint="prepared-old-certificate",
            )
        )
        self.state.runtime_store.delete_thread(prepared.session_id)
        for session_id, include_rollout in (
            (source.session_id, True),
            (prepared.session_id, False),
        ):
            codex_home = (
                self.root
                / "workspaces"
                / "default"
                / "runtime"
                / "sessions"
                / session_id
                / "codex-home"
            )
            codex_home.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(codex_home / "state_5.sqlite")) as connection:
                connection.execute("CREATE TABLE provider_state (value TEXT)")
                connection.commit()
            if include_rollout:
                rollout = codex_home / "sessions" / "rollout.jsonl"
                rollout.parent.mkdir(parents=True)
                rollout.write_text('{"event":"preserved"}\n', encoding="utf-8")

        with (
            patch.dict(
                os.environ,
                {"MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS": "1"},
                clear=False,
            ),
            patch.object(
                installation.inspector,
                "artifact",
                return_value=installation.runtime_artifact,
            ),
        ):
            restarted = bootstrap_platform_state(
                start_path=self.root,
                now=NOW + timedelta(seconds=1),
                install_builtin_apps=False,
            )

        thread = restarted.runtime_store.get_thread(source.session_id)
        self.assertNotEqual(thread.runtime_session_id, source.session_id)
        self.assertEqual(
            restarted.runtime_store.get_session(thread.runtime_session_id).predecessor_session_id,
            source.session_id,
        )
        persisted_prepared = restarted.runtime_store.get_session(prepared.session_id)
        self.assertEqual(persisted_prepared.thread_visibility, "hidden")
        self.assertEqual(
            persisted_prepared.prepared_session_fingerprint,
            "prepared-old-certificate",
        )
        with self.assertRaises(RuntimeThreadNotFoundError):
            restarted.runtime_store.get_thread(prepared.session_id)
        snapshots = list((self.root / "data" / "recovery-snapshots").iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertTrue((snapshots[0] / "manifest.json").is_file())

    def test_existing_turn_admits_compatible_successor_before_capability_preflight(self):
        historical_projection, _historical_root, installation, codex = (
            self._install_historical_projection()
        )
        source = self._source_session(
            "turn-preflight-history",
            target_workspace_binding_id=codex.binding_id,
            source_certificate=historical_projection,
        )
        app = PlatformHost(self.state, start_path=self.root)
        cookie = self._login(app)
        preflight_session_ids: list[str] = []

        def capability_preflight(_state, *, session, **_kwargs):
            preflight_session_ids.append(session.session_id)
            if session.session_id == source.session_id:
                raise CapabilityCertificateError("adapter_artifact_mismatch")
            return None

        def queue_without_worker(
            submit_state,
            *,
            session,
            input_text,
            client_message_id=None,
            attachments=None,
            app_references=None,
            on_queued=None,
            turn_id=None,
            received_perf_counter=None,
            submission_timing=None,
            **_kwargs,
        ):
            turn, events = _queue_turn_with_event(
                submit_state,
                session=session,
                input_text=input_text,
                provider_id="codex",
                client_message_id=client_message_id,
                attachments=attachments,
                app_references=app_references,
                turn_id=turn_id,
                received_perf_counter=received_perf_counter,
                submission_timing=submission_timing,
            )
            if on_queued is not None:
                on_queued(turn, events)
            return turn, events

        with (
            patch.object(
                installation.inspector,
                "artifact",
                return_value=installation.runtime_artifact,
            ),
            patch(
                "core.api.runtime_api.preflight_runtime_context_capabilities",
                side_effect=capability_preflight,
            ),
            patch(
                "core.api.runtime_api.submit_runtime_turn_async",
                side_effect=queue_without_worker,
            ),
            patch(
                "core.runtime.turn_submission_service_queue.schedule_runtime_thread_title_generation"
            ),
        ):
            status, payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{source.session_id}/turns",
                method="POST",
                body={
                    "input_text": "continue on the current certificate",
                    "client_message_id": "turn-after-certificate-rollout",
                    "async": True,
                },
                cookie=cookie,
            )

        successor_id = payload["session"]["session_id"]
        self.assertEqual(status, 202)
        self.assertNotEqual(successor_id, source.session_id)
        self.assertEqual(preflight_session_ids, [successor_id])
        self.assertEqual(
            self.state.runtime_store.get_thread(source.session_id).runtime_session_id,
            successor_id,
        )
        self.assertEqual(self.state.runtime_store.list_turns(source.session_id), [])
        self.assertEqual(len(self.state.runtime_store.list_turns(successor_id)), 1)

    def test_existing_prewarm_admits_compatible_successor(self):
        historical_projection, _historical_root, installation, codex = (
            self._install_historical_projection()
        )
        source = self._source_session(
            "prewarm-admission-history",
            target_workspace_binding_id=codex.binding_id,
            source_certificate=historical_projection,
        )
        app = PlatformHost(self.state, start_path=self.root)
        cookie = self._login(app)
        prewarm_result = RuntimeSessionPrewarmResult(
            status="ready",
            prewarm_completed=True,
            provider_thread_ready=True,
            runtime_ready=True,
            provider_id="codex",
        )

        with (
            patch.object(
                installation.inspector,
                "artifact",
                return_value=installation.runtime_artifact,
            ),
            patch(
                "core.api.runtime_api._prewarm_new_runtime_session",
                return_value=prewarm_result,
            ) as prewarm,
        ):
            status, payload, _headers = self._invoke(
                app,
                path=f"/api/runtime/sessions/{source.session_id}/prewarm",
                method="POST",
                body={},
                cookie=cookie,
            )

        successor_id = payload["session_id"]
        self.assertEqual(status, 200)
        self.assertNotEqual(successor_id, source.session_id)
        self.assertEqual(prewarm.call_args.args[1].session_id, successor_id)
        self.assertEqual(
            self.state.runtime_store.get_thread(source.session_id).runtime_session_id,
            successor_id,
        )

    def test_rollout_repairs_other_chats_when_one_snapshot_fails(self):
        historical_projection, _historical_root, installation, codex = (
            self._install_historical_projection()
        )
        sources = [
            self._source_session(
                session_id,
                target_workspace_binding_id=codex.binding_id,
                source_certificate=historical_projection,
            )
            for session_id in (
                "rollout-corrupt-history",
                "rollout-valid-history-a",
                "rollout-valid-history-b",
            )
        ]
        for source in sources:
            codex_home = (
                self.root
                / "workspaces"
                / "default"
                / "runtime"
                / "sessions"
                / source.session_id
                / "codex-home"
            )
            codex_home.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(codex_home / "state_5.sqlite")) as connection:
                connection.execute("CREATE TABLE provider_state (value TEXT)")
                connection.commit()
            if source.session_id != "rollout-corrupt-history":
                rollout = codex_home / "sessions" / "rollout.jsonl"
                rollout.parent.mkdir(parents=True)
                rollout.write_text('{"event":"preserved"}\n', encoding="utf-8")

        with patch.object(
            installation.inspector,
            "artifact",
            return_value=installation.runtime_artifact,
        ):
            result = repair_runtime_continuations_after_certified_rollout(
                self.state,
                now=NOW + timedelta(seconds=1),
            )

        workspace = result["workspaces"][0]
        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["repaired_count"], 2)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(
            workspace["failures"][0]["session_id"],
            "rollout-corrupt-history",
        )
        self.assertEqual(
            self.state.runtime_store.get_thread(
                "rollout-corrupt-history"
            ).runtime_session_id,
            "rollout-corrupt-history",
        )
        for source in sources[1:]:
            self.assertNotEqual(
                self.state.runtime_store.get_thread(
                    source.session_id
                ).runtime_session_id,
                source.session_id,
            )
        snapshots = list((self.root / "data" / "recovery-snapshots").iterdir())
        self.assertEqual(len(snapshots), 2)
        self.assertTrue(
            all((snapshot / "manifest.json").is_file() for snapshot in snapshots)
        )

if __name__ == "__main__":
    unittest.main()
