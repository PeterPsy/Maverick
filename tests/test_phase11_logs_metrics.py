"""Split tests from tests/test_phase11_observability.py."""

from __future__ import annotations

from tests.phase11_observability_helpers import *


class TestPhase11LogsMetrics(Phase11ObservabilityBase):
    """Focused test slice."""

    def test_observability_store_records_redacted_event_audit_and_metrics(self) -> None:
        store = self.make_observability_store()

        event = emit_structured_event(
            store,
            event_type="secret.resolution",
            event_plane="platform",
            source_domain="secrets",
            workspace_id="default",
            payload={"secret_ref": "platform:secrets/openai", "result": "ok"},
        )
        audit = record_audit_event(
            store,
            action="secret.rotate",
            status="succeeded",
            source_domain="secrets",
            detail="operator rotated secret",
            workspace_id="default",
            payload={"raw_value": "sk-secret", "secret_id": "openai"},
        )
        metric = record_metric(
            store,
            metric_name="recovery.intent.count",
            kind="counter",
            value=1,
            workspace_id="default",
            tags={"source_domain": "recovery"},
        )

        self.assertEqual(event.payload["secret_ref"], "<redacted>")
        self.assertEqual(audit.payload["raw_value"], "<redacted>")
        self.assertEqual(metric.metric_name, "recovery.intent.count")
        self.assertEqual(len(store.list_events(workspace_id="default")), 1)
        self.assertEqual(len(store.list_audit(workspace_id="default")), 1)
        self.assertEqual(len(store.list_metrics(workspace_id="default")), 1)

    def test_runtime_log_roots_and_retention_are_applied(self) -> None:
        repo_root = self.make_repo_root()
        roots = ensure_observability_roots(workspace_id="default", app_id="chat", start_path=repo_root)
        self.assertTrue(roots["platform"].is_dir())
        self.assertTrue(roots["runtime"].is_dir())
        self.assertTrue(roots["workspace"].is_dir())
        self.assertTrue(roots["app"].is_dir())

        for index in range(22):
            stale = roots["platform"] / f"platform-old-{index:02d}.jsonl"
            stale.write_text("{}", encoding="utf-8")
        apply_retention(log_root=roots["platform"], max_files=20)
        self.assertLessEqual(len(list(roots["platform"].iterdir())), 20)

        record = append_runtime_log(
            log_plane="app",
            workspace_id="default",
            app_id="chat",
            runtime_session_id="sess-1",
            provider_id="codex",
            message="runtime env prepared",
            payload={"api_key": "secret", "workspace_id": "default"},
            start_path=repo_root,
        )
        self.assertIn("/workspaces/default/logs/apps/chat/", record.log_path)
        log_content = Path(record.log_path).read_text(encoding="utf-8")
        self.assertIn("<redacted>", log_content)
        self.assertNotIn("secret", log_content)
