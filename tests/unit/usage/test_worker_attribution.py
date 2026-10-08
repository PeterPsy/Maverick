"""Internal operator metering stays complete without changing Chat presentation."""

from datetime import UTC, datetime, timedelta
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from core.runtime.runtime_session import RuntimeSessionRecord
from core.shared.in_memory_collection import InMemoryCollection
from core.usage.payloads import chat_usage_summary_payload, runtime_usage_diagnostic_payload
from core.usage.service import ingest_runtime_usage
from core.usage.store import UsageCollections, UsageDocumentStore
from core.usage.sqlite_store import UsageSqliteStore


class WorkerUsageTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(tz=UTC)
        self.session = RuntimeSessionRecord(session_id="root", workspace_id="default", agent_id="chat",
            status="running", requested_mode="full-access", effective_mode="full-access", workspace_root="/workspace",
            workdir="/workspace", runtime_root="/runtime", started_at=self.now, updated_at=self.now,
            ended_at=None, last_progress_at=None, provider_id="codex")
        self.store = UsageDocumentStore(UsageCollections(samples=InMemoryCollection(),
            buckets=InMemoryCollection(), quota_snapshots=InMemoryCollection()))
        self.state = SimpleNamespace(usage_store=self.store,
            runtime_store=SimpleNamespace(get_session=lambda sid: self.session), provider_registry=None)

    def ingest(self, payload, seconds=0):
        return ingest_runtime_usage(self.state, session_id="root", turn_id="root-turn",
            payload=payload, observed_at=self.now + timedelta(seconds=seconds))

    def actor_usage(self, thread="actor-1", total=200):
        return {"usage_worker": "computer_actor", "usage_id": thread + ":" + str(total),
            "provider_id": "codex", "model_id": "gpt-6-luna", "source": "codex_computer_actor:" + thread,
            "semantics": "cumulative", "input_tokens": total - 20, "cached_input_tokens": 80,
            "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": total,
            "latest_input_tokens": total - 20, "latest_cached_input_tokens": 80,
            "latest_output_tokens": 20, "latest_reasoning_output_tokens": 5, "latest_total_tokens": total,
            "context_tokens": None, "context_accuracy": "unavailable"}

    def test_operator_totals_are_delegated_but_chat_identity_and_context_stay_main(self):
        self.ingest({"usage_id": "main", "provider_id": "codex", "model_id": "gpt-6.1-sol",
            "source": "codex_app_server", "semantics": "incremental", "input_tokens": 100,
            "output_tokens": 10, "total_tokens": 110, "context_tokens": 100, "context_accuracy": "exact"})
        result = self.ingest(self.actor_usage(), 1)
        self.assertEqual(result.summary.tokens.total_tokens, 310)
        self.assertEqual(result.summary.delegated_tokens.total_tokens, 200)
        self.assertEqual(result.summary.context_tokens, 100)
        visible = chat_usage_summary_payload(result.summary)
        self.assertEqual(visible["model_ids"], ["gpt-6.1-sol"])
        self.assertEqual(visible["direct_tokens"]["total_tokens"], 310)
        self.assertEqual(visible["delegated_tokens"]["total_tokens"], 0)
        self.assertIn("gpt-6-luna", runtime_usage_diagnostic_payload(result.summary)["model_ids"])

    def test_repeated_snapshots_are_idempotent_and_new_contexts_do_not_share_baselines(self):
        first = self.ingest(self.actor_usage())
        repeated = self.ingest(self.actor_usage(), 1)
        second = self.ingest(self.actor_usage("actor-2"), 2)
        self.assertTrue(first.inserted)
        self.assertFalse(repeated.inserted)
        self.assertEqual(second.summary.tokens.total_tokens, 400)
        self.assertEqual(second.sample.session_id, "root:computer_actor")

    def test_unknown_worker_claim_does_not_change_session_attribution(self):
        payload = self.actor_usage()
        payload["source"] = "untrusted"
        result = self.ingest(payload)
        self.assertEqual(result.sample.session_id, "root")

    def test_parent_cleanup_removes_internal_worker_streams(self):
        self.ingest(self.actor_usage())
        self.assertEqual(self.store.delete_sessions(["root"]), {"root": 1})
        self.assertEqual(self.store.list_samples(root_session_id="root"), [])

    def test_child_worker_keeps_its_owning_agent_consumption_delegated(self):
        child = replace(self.session, session_id="child", creator_runtime_session_id="root")
        self.state.runtime_store.get_session = lambda sid: child if sid == "child" else self.session
        result = ingest_runtime_usage(self.state, session_id="child", turn_id="child-turn",
            payload=self.actor_usage(), observed_at=self.now)
        visible = chat_usage_summary_payload(result.summary)
        self.assertEqual(visible["direct_tokens"]["total_tokens"], 0)
        self.assertEqual(visible["delegated_tokens"]["total_tokens"], 200)
        self.assertNotIn("gpt-6-luna", visible["model_ids"])


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), "Requires the verified WAL-safe runtime")
class WorkerUsageSqliteTests(WorkerUsageTests):
    def setUp(self):
        super().setUp()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.store = UsageSqliteStore(Path(scratch.name) / "usage.sqlite")
        self.store.initialize()
        self.state.usage_store = self.store
