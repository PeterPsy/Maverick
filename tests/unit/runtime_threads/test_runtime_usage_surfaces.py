"""Usage diagnostics preserve transcript authority and numeric cache accounting."""

from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from core.cli.models import CliInvocationContext
from core.cli.service import run_core_cli_command
from core.mcp.models import McpInvocationContext
from core.mcp.service import call_mcp_tool
from core.runtime.errors import RuntimeTranscriptAccessError, RuntimeTranscriptValidationError
from core.runtime.output_compaction.redaction import redact_payload
from core.runtime.transcript_models import RuntimeTranscriptReadContext
from core.runtime.usage_read import read_runtime_usage
from core.shared.in_memory_collection import InMemoryCollection
from core.usage.service import ingest_runtime_usage
from core.usage.store import UsageCollections, UsageDocumentStore
from core.usage.sqlite_store import UsageSqliteStore
from tests.unit.runtime_threads import test_runtime_transcript_surfaces as fixtures


class RuntimeUsageSurfaceTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.RuntimeTranscriptSurfaceTest()
        fixture.setUp()
        self.runtime = fixture.store
        self.usage = UsageDocumentStore(UsageCollections(
            samples=InMemoryCollection(), buckets=InMemoryCollection(), quota_snapshots=InMemoryCollection()))
        state = SimpleNamespace(runtime_store=self.runtime, usage_store=self.usage, provider_registry=None)
        self.sample = ingest_runtime_usage(state, session_id="session-1", turn_id="turn-1", observed_at=fixtures.NOW,
            payload={"usage_id": "one", "provider_id": "codex", "model_id": "gpt-test",
                     "semantics": "incremental", "token_accuracy": "exact", "context_accuracy": "exact",
                     "input_tokens": 100, "cached_input_tokens": 25, "output_tokens": 20,
                     "reasoning_output_tokens": 5, "total_tokens": 120,
                     "context_tokens": 100, "context_window_tokens": 200}).sample
        self.context = RuntimeTranscriptReadContext(workspace_id="default", user_id="alice",
            platform_role="member", workspace_role="member", caller_runtime_session_id="caller")

    def read(self, **args):
        return read_runtime_usage(self.runtime, usage_store=self.usage, context=self.context,
                                  thread_id="session-1", **args)

    def test_usage_counts_survive_credential_redaction_in_both_surfaces(self):
        fields = dict(caller_kind="sandbox_agent", workspace_id="default", agent_id="caller",
            effective_mode="sandbox", platform_role="member", user_id="alice", workspace_role="member",
            runtime_session_id="caller")
        args = {"thread_id": "session-1"}
        cli = run_core_cli_command(command_id="core.runtime.usage.read", context=CliInvocationContext(**fields),
            runtime_store=self.runtime, usage_store=self.usage, arguments=args)
        mcp = call_mcp_tool(tool_name="core.runtime.usage.read", context=McpInvocationContext(**fields),
            runtime_store=self.runtime, usage_store=self.usage, arguments=args)
        for result in (cli, mcp):
            safe = redact_payload({**result, "access_token": "credential"})
            self.assertEqual(safe["access_token"], "<redacted>")
            counts = safe["usage"]["counts"]
            self.assertEqual(counts["processed"], 120)
            self.assertEqual(counts["cached_input"], 25)
            self.assertEqual(counts["non_cached"], 95)
            self.assertEqual(sum(counts[key] for key in ("uncached_input", "cached_input", "cache_write_input", "output", "reasoning_output")), 120)
            self.assertEqual(safe["usage"]["active_context"]["used_percent"], 50)
            self.assertEqual(safe["usage"]["accuracy"], "exact")

    def test_turn_scope_and_absent_samples_are_explicit(self):
        result = self.read(turn_id="turn-1")
        self.assertEqual(result["scope"], "direct_turn")
        self.assertEqual(result["usage"]["counts"]["processed"], 120)
        self.runtime.save_turn(replace(self.runtime.list_turns("session-1")[0], turn_id="turn-empty"))
        empty = self.read(turn_id="turn-empty")["usage"]
        self.assertEqual(empty["accuracy"], "unavailable")
        self.assertEqual(empty["sample_count"], 0)
        with self.assertRaises(RuntimeTranscriptValidationError):
            self.read(turn_id="another-chat-turn")

    def test_chat_includes_delegation_while_turn_accounting_stays_direct(self):
        self.runtime.save_session(replace(self.runtime.get_session("session-1"), session_id="child",
                                         creator_runtime_session_id="session-1", session_kind="inter_agent_participant",
                                         thread_visibility="hidden"))
        ingest_runtime_usage(SimpleNamespace(runtime_store=self.runtime, usage_store=self.usage, provider_registry=None),
            session_id="child", turn_id="child-turn", observed_at=fixtures.NOW,
            payload={"usage_id": "child-one", "provider_id": "codex", "semantics": "incremental",
                     "input_tokens": 8, "output_tokens": 2, "total_tokens": 10, "token_accuracy": "exact"})
        usage = self.read()["usage"]
        self.assertEqual(usage["counts"]["processed"], 130)
        self.assertEqual(usage["direct"]["processed"], 120)
        self.assertEqual(usage["delegated"]["processed"], 10)
        self.assertEqual(self.read(turn_id="turn-1")["usage"]["counts"]["processed"], 120)

    def test_cross_owner_and_workspace_reads_fail_before_usage_access(self):
        for context in [replace(self.context, user_id="bob"), replace(self.context, workspace_id="another")]:
            with self.assertRaises(RuntimeTranscriptAccessError):
                read_runtime_usage(self.runtime, usage_store=self.usage, context=context, thread_id="session-1")
        with self.assertRaisesRegex(RuntimeTranscriptAccessError, "runtime_usage_unavailable"):
            read_runtime_usage(self.runtime, usage_store=None, context=self.context, thread_id="session-1")

    def test_turn_includes_only_its_internal_operator_usage(self):
        state = SimpleNamespace(runtime_store=self.runtime, usage_store=self.usage, provider_registry=None)
        worker = {"usage_worker": "computer_actor", "provider_id": "codex", "model_id": "gpt-6-luna",
                  "source": "codex_computer_actor:operator", "semantics": "incremental",
                  "input_tokens": 180, "output_tokens": 20, "total_tokens": 200, "token_accuracy": "exact"}
        ingest_runtime_usage(state, session_id="session-1", turn_id="turn-1", observed_at=fixtures.NOW,
                             payload={**worker, "usage_id": "operator-one"})
        ingest_runtime_usage(state, session_id="session-1", turn_id="another-turn", observed_at=fixtures.NOW,
                             payload={**worker, "usage_id": "operator-other"})
        usage = self.read(turn_id="turn-1")["usage"]
        self.assertEqual(usage["counts"]["processed"], 320)
        self.assertEqual(usage["direct"]["processed"], 120)
        self.assertEqual(usage["delegated"]["processed"], 200)
        self.assertEqual(usage["sample_count"], 2)
        self.assertEqual(usage["active_context"]["used"], 100)
        self.assertIn("gpt-6-luna", usage["model_ids"])


@unittest.skipIf(sqlite3.sqlite_version_info < (3, 51, 3), "Requires the verified WAL-safe runtime")
class RuntimeUsageSqliteSurfaceTests(RuntimeUsageSurfaceTests):
    def setUp(self):
        super().setUp()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        store = UsageSqliteStore(Path(scratch.name) / "usage.sqlite")
        store.initialize()
        store.save_sample_if_absent(self.sample)
        self.usage = store
