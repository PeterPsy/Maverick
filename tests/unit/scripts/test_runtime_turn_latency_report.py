from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "runtime_turn_latency_report.py"
SPEC = importlib.util.spec_from_file_location("runtime_turn_latency_report", SCRIPT_PATH)
assert SPEC is not None
runtime_turn_latency_report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = runtime_turn_latency_report
SPEC.loader.exec_module(runtime_turn_latency_report)


BASE = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


class RuntimeTurnLatencyReportTestCase(unittest.TestCase):
    def test_groups_codex_cold_warm_and_plain_hosted_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-codex", runtime_mode="agentic", provider_id="codex")
            _write_events(
                root,
                "default",
                "sess-codex",
                [
                    *_turn_events("sess-codex", "turn-cold", BASE, provider_id="codex", ensure_runtime_ms=250, ensure_provider_thread_ms=900),
                    *_turn_events(
                        "sess-codex",
                        "turn-warm",
                        BASE + timedelta(minutes=1),
                        provider_id="codex",
                        ensure_runtime_ms=0.05,
                        ensure_provider_thread_ms=0.01,
                    ),
                ],
            )
            _write_session(root, "default", "sess-hosted", runtime_mode="plain_hosted_chat", provider_id="openrouter")
            _write_events(
                root,
                "default",
                "sess-hosted",
                [
                    *_turn_events(
                        "sess-hosted",
                        "turn-hosted",
                        BASE + timedelta(minutes=2),
                        provider_id="openrouter",
                        runtime_mode="plain_hosted_chat",
                        include_launch_metrics=False,
                    )
                ],
            )

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0)

        self.assertEqual(report["summary"]["turns_reported"], 3)
        self.assertEqual(report["cohorts"]["codex_cold"]["turn_count"], 1)
        self.assertEqual(report["cohorts"]["codex_warm"]["turn_count"], 1)
        self.assertEqual(report["cohorts"]["plain_hosted"]["turn_count"], 1)
        self.assertEqual(report["cohorts"]["plain_hosted"]["slo_scope"], "hosted_http_provider")
        cold_metrics = report["cohorts"]["codex_cold"]["metrics"]
        warm_metrics = report["cohorts"]["codex_warm"]["metrics"]
        hosted_metrics = report["cohorts"]["plain_hosted"]["metrics"]
        self.assertEqual(cold_metrics["ensure_runtime_ms"]["p50_ms"], 250)
        self.assertEqual(warm_metrics["ensure_runtime_ms"]["p50_ms"], 0.05)
        self.assertEqual(hosted_metrics["turn_start_sent_to_provider_accepted_ms"]["p50_ms"], 20)
        self.assertEqual(cold_metrics["receive_to_provider_accepted_ms"]["p50_ms"], 830)

    def test_reads_history_and_deduplicates_tail_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-history", runtime_mode="agentic", provider_id="codex")
            events = _turn_events("sess-history", "turn-1", BASE, provider_id="codex")
            _write_events(root, "default", "sess-history", events[-2:])
            _write_events(root, "default", "sess-history", events, history=True)

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0, include_turns=True)

        self.assertEqual(report["summary"]["events_loaded"], 6)
        self.assertEqual(report["summary"]["duplicate_events_skipped"], 2)
        self.assertEqual(report["summary"]["turns_reported"], 1)
        self.assertEqual(report["turns"][0]["metrics"]["queued_to_worker_started_ms"], 200)

    def test_since_filters_on_turn_anchor_without_reclassifying_warm_turn_as_cold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-codex", runtime_mode="agentic", provider_id="codex")
            _write_events(
                root,
                "default",
                "sess-codex",
                [
                    *_turn_events("sess-codex", "turn-cold", BASE, provider_id="codex", ensure_runtime_ms=250),
                    *_turn_events("sess-codex", "turn-warm", BASE + timedelta(minutes=10), provider_id="codex", ensure_runtime_ms=0.05, ensure_provider_thread_ms=0.01),
                ],
            )

            report = runtime_turn_latency_report.build_report(
                root,
                workspaces={"default"},
                since=BASE + timedelta(minutes=5),
                limit_turns=0,
            )

        self.assertEqual(report["cohorts"]["codex_cold"]["turn_count"], 0)
        self.assertEqual(report["cohorts"]["codex_warm"]["turn_count"], 1)


def _write_session(root: Path, workspace_id: str, session_id: str, *, runtime_mode: str, provider_id: str) -> None:
    session_root = root / "workspaces" / workspace_id / "runtime" / "sessions" / session_id
    session_root.mkdir(parents=True, exist_ok=True)
    _write_collection(
        session_root / "session.json",
        [
            {
                "workspace_id": workspace_id,
                "session_id": session_id,
                "runtime_mode": runtime_mode,
                "provider_id": provider_id,
            }
        ],
    )


def _write_events(root: Path, workspace_id: str, session_id: str, events: list[dict[str, object]], *, history: bool = False) -> None:
    session_root = root / "workspaces" / workspace_id / "runtime" / "sessions" / session_id
    if history:
        path = session_root / "events-history" / "000000.json"
    else:
        path = session_root / "events.json"
    _write_collection(path, events)


def _write_collection(path: Path, documents: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(documents, indent=2) + "\n", encoding="utf-8")


def _turn_events(
    session_id: str,
    turn_id: str,
    start: datetime,
    *,
    provider_id: str,
    runtime_mode: str = "agentic",
    ensure_runtime_ms: float = 10,
    ensure_provider_thread_ms: float = 15,
    include_launch_metrics: bool = True,
) -> list[dict[str, object]]:
    workspace_id = "default"
    queued_at = start
    receive_metric_at = start + timedelta(milliseconds=50)
    worker_at = start + timedelta(milliseconds=200)
    dispatch_at = start + timedelta(milliseconds=450)
    sent_at = start + timedelta(milliseconds=760)
    accepted_at = start + timedelta(milliseconds=780)
    dispatch_payload: dict[str, object] = {"provider_id": provider_id, "runtime_mode": runtime_mode}
    if include_launch_metrics:
        dispatch_payload.update({"launch_spec_ms": 25, "skill_resolve_ms": 5, "skill_prepare_ms": 15})
    return [
        _event("queued", workspace_id, session_id, turn_id, "runtime.turn.queued", queued_at, {"provider_id": provider_id}),
        _event(
            "receive",
            workspace_id,
            session_id,
            turn_id,
            "runtime.turn.receive_to_queued",
            receive_metric_at,
            {"receive_to_queued_ms": 50},
        ),
        _event("worker", workspace_id, session_id, turn_id, "runtime.turn.worker_started", worker_at, {"provider_id": provider_id}),
        _event("dispatch", workspace_id, session_id, turn_id, "runtime.provider.dispatching", dispatch_at, dispatch_payload),
        _event(
            "sent",
            workspace_id,
            session_id,
            turn_id,
            "runtime.provider.turn_start_sent",
            sent_at,
            {
                "provider_id": provider_id,
                "runtime_mode": runtime_mode,
                "ensure_runtime_ms": ensure_runtime_ms,
                "ensure_provider_thread_ms": ensure_provider_thread_ms,
            },
        ),
        _event(
            "accepted",
            workspace_id,
            session_id,
            turn_id,
            "runtime.provider.accepted",
            accepted_at,
            {
                "provider_id": provider_id,
                "runtime_mode": runtime_mode,
                "turn_start_to_ack_ms": 20,
                "ensure_runtime_ms": ensure_runtime_ms,
                "ensure_provider_thread_ms": ensure_provider_thread_ms,
            },
        ),
    ]


def _event(
    prefix: str,
    workspace_id: str,
    session_id: str,
    turn_id: str,
    event_type: str,
    created_at: datetime,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "event_id": f"{turn_id}-{prefix}",
        "workspace_id": workspace_id,
        "session_id": session_id,
        "plane": "turn",
        "event_type": event_type,
        "turn_id": turn_id,
        "process_id": None,
        "payload": payload,
        "created_at": {runtime_turn_latency_report.DATETIME_MARKER: created_at.isoformat()},
    }


if __name__ == "__main__":
    unittest.main()
