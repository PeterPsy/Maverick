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
                    *_turn_events(
                        "sess-codex",
                        "turn-cold",
                        BASE,
                        provider_id="codex",
                        ensure_runtime_ms=250,
                        ensure_provider_thread_ms=900,
                        prewarm_wait_ms=175,
                        prewarm_total_ms=640,
                    ),
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
        self.assertEqual(cold_metrics["claim_ms"]["p50_ms"], 1)
        self.assertEqual(cold_metrics["post_queue_response_ms"]["p50_ms"], 10)
        self.assertEqual(cold_metrics["prewarm_wait_ms"]["p50_ms"], 175)
        self.assertEqual(cold_metrics["prewarm_total_ms"]["p50_ms"], 640)
        self.assertEqual(cold_metrics["first_turn_receive_to_provider_accepted_ms"]["p50_ms"], 830)
        self.assertEqual(warm_metrics["ensure_runtime_ms"]["p50_ms"], 0.05)
        self.assertEqual(hosted_metrics["turn_start_sent_to_provider_accepted_ms"]["p50_ms"], 20)
        self.assertEqual(cold_metrics["receive_to_provider_accepted_ms"]["p50_ms"], 830)

    def test_calculates_worker_reference_and_provider_input_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-refs", runtime_mode="agentic", provider_id="codex")
            turn_id = "turn-refs"
            _write_events(
                root,
                "default",
                "sess-refs",
                [
                    _event(
                        "queued",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.queued",
                        BASE,
                        {
                            "provider_id": "codex",
                            "app_references": [
                                {"type": "entity", "app_id": "storage", "entity_type": "file", "entity_id": "file-1"},
                                {"type": "entity", "app_id": "crm", "entity_type": "account", "entity_id": "acct-1"},
                            ],
                            "attachments": [
                                {"kind": "image", "workspace_relative_path": "storage/uploaded/photo.jpg"},
                            ],
                        },
                    ),
                    _event(
                        "thread-catalog-start",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.thread_user_message_queued_started",
                        BASE + timedelta(milliseconds=10),
                        {"provider_id": "codex", "attachment_count": 1, "app_reference_count": 2, "storage_reference_count": 1},
                    ),
                    _event(
                        "thread-catalog-complete",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.thread_user_message_queued_completed",
                        BASE + timedelta(milliseconds=23),
                        {"provider_id": "codex", "thread_catalog_queued_ms": 13, "attachment_count": 1, "app_reference_count": 2, "storage_reference_count": 1},
                    ),
                    _event("worker-entered", "default", "sess-refs", turn_id, "runtime.turn.worker_entered", BASE + timedelta(milliseconds=75), {"provider_id": "codex"}),
                    _event("prewarm-start", "default", "sess-refs", turn_id, "runtime.turn.prewarm_wait_started", BASE + timedelta(milliseconds=80), {"provider_id": "codex"}),
                    _event(
                        "prewarm-complete",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.prewarm_wait_completed",
                        BASE + timedelta(milliseconds=105),
                        {"provider_id": "codex", "prewarm_wait_ms": 25, "prewarm_total_ms": 150, "completed": True},
                    ),
                    _event("lock-start", "default", "sess-refs", turn_id, "runtime.turn.session_lock_wait_started", BASE + timedelta(milliseconds=110), {"provider_id": "codex"}),
                    _event(
                        "lock-acquired",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.session_lock_acquired",
                        BASE + timedelta(milliseconds=130),
                        {"provider_id": "codex", "session_lock_wait_ms": 20},
                    ),
                    _event(
                        "debug-log",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.debug_log_completed",
                        BASE + timedelta(milliseconds=130.5),
                        {"provider_id": "codex", "phase": "async_worker_entered", "debug_log_runtime_turn_ms": 0.5},
                    ),
                    _event(
                        "turn-lookup",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.worker_turn_lookup_completed",
                        BASE + timedelta(milliseconds=130.8),
                        {"provider_id": "codex", "phase": "pre_cancel_check", "worker_turn_lookup_ms": 1.5},
                    ),
                    _event(
                        "source-dispatch-start",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.source_app_queued_dispatch_started",
                        BASE + timedelta(milliseconds=131),
                        {"provider_id": "codex"},
                    ),
                    _event(
                        "source-dispatch-complete",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.source_app_queued_dispatch_completed",
                        BASE + timedelta(milliseconds=133),
                        {"provider_id": "codex", "source_app_queued_dispatch_ms": 2},
                    ),
                    _event(
                        "activation",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.turn_activation_completed",
                        BASE + timedelta(milliseconds=135),
                        {
                            "provider_id": "codex",
                            "status": "active",
                            "transition_active_ms": 3,
                            "save_state_ms": 0.8,
                            "save_session_ms": 0.7,
                            "save_turn_ms": 0.6,
                            "thread_update_ms": 0.9,
                        },
                    ),
                    _event(
                        "turn-started-recorded",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.turn_started_recorded",
                        BASE + timedelta(milliseconds=136),
                        {"provider_id": "codex", "turn_started_record_ms": 1},
                    ),
                    _event("availability-start", "default", "sess-refs", turn_id, "runtime.turn.thread_availability_started", BASE + timedelta(milliseconds=137), {"provider_id": "codex", "availability": "active"}),
                    _event(
                        "availability-complete",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.thread_availability_completed",
                        BASE + timedelta(milliseconds=144),
                        {"provider_id": "codex", "availability": "active", "thread_availability_update_ms": 7},
                    ),
                    _event("worker", "default", "sess-refs", turn_id, "runtime.turn.worker_started", BASE + timedelta(milliseconds=145), {"provider_id": "codex"}),
                    _event(
                        "worker-started-recorded",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.worker_started_recorded",
                        BASE + timedelta(milliseconds=146),
                        {"provider_id": "codex", "worker_started_record_ms": 0.8},
                    ),
                    _event(
                        "session-lookup",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.worker_session_lookup_completed",
                        BASE + timedelta(milliseconds=147),
                        {"provider_id": "codex", "phase": "before_execution", "worker_session_lookup_ms": 1.2},
                    ),
                    _event(
                        "refs-start",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.app_references_materialize_started",
                        BASE + timedelta(milliseconds=160),
                        {"provider_id": "codex", "app_reference_count": 2, "storage_reference_count": 1},
                    ),
                    _event(
                        "refs-complete",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.app_references_materialize_completed",
                        BASE + timedelta(milliseconds=220),
                        {
                            "provider_id": "codex",
                            "app_reference_materialize_ms": 60,
                            "app_reference_count": 2,
                            "storage_reference_count": 1,
                            "materialized_reference_count": 1,
                            "reference_cache_hit": False,
                        },
                    ),
                    _event(
                        "input-start",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.provider_input_started",
                        BASE + timedelta(milliseconds=225),
                        {"provider_id": "codex", "app_reference_count": 2, "storage_reference_count": 1, "materialized_reference_count": 1},
                    ),
                    _event(
                        "input-complete",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.turn.provider_input_completed",
                        BASE + timedelta(milliseconds=240),
                        {"provider_id": "codex", "provider_input_build_ms": 15, "app_reference_count": 2, "storage_reference_count": 1, "materialized_reference_count": 1},
                    ),
                    _event(
                        "dispatch",
                        "default",
                        "sess-refs",
                        turn_id,
                        "runtime.provider.dispatching",
                        BASE + timedelta(milliseconds=260),
                        {"provider_id": "codex", "runtime_mode": "agentic"},
                    ),
                    _event("sent", "default", "sess-refs", turn_id, "runtime.provider.turn_start_sent", BASE + timedelta(milliseconds=300), {"provider_id": "codex", "runtime_mode": "agentic", "ensure_runtime_ms": 0.01}),
                    _event("accepted", "default", "sess-refs", turn_id, "runtime.provider.accepted", BASE + timedelta(milliseconds=330), {"provider_id": "codex", "runtime_mode": "agentic", "turn_start_to_ack_ms": 30}),
                ],
            )

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0, include_turns=True)

        metrics = report["turns"][0]["metrics"]
        self.assertEqual(metrics["queued_to_worker_entered_ms"], 75)
        self.assertEqual(metrics["queued_to_worker_started_ms"], 145)
        self.assertEqual(metrics["worker_entered_to_worker_started_ms"], 70)
        self.assertEqual(metrics["worker_entered_to_started_unattributed_ms"], 7.0)
        self.assertEqual(metrics["source_app_queued_dispatch_ms"], 2)
        self.assertEqual(metrics["debug_log_runtime_turn_ms"], 0.5)
        self.assertEqual(metrics["worker_turn_lookup_ms"], 1.5)
        self.assertEqual(metrics["turn_started_record_ms"], 1)
        self.assertEqual(metrics["worker_started_record_ms"], 0.8)
        self.assertEqual(metrics["worker_session_lookup_ms"], 1.2)
        self.assertEqual(metrics["transition_active_ms"], 3)
        self.assertEqual(metrics["save_state_ms"], 0.8)
        self.assertEqual(metrics["save_session_ms"], 0.7)
        self.assertEqual(metrics["save_turn_ms"], 0.6)
        self.assertEqual(metrics["thread_update_ms"], 0.9)
        self.assertEqual(metrics["thread_catalog_queued_ms"], 13)
        self.assertEqual(metrics["thread_availability_update_ms"], 7)
        self.assertEqual(metrics["turn_started_to_worker_started_ms"], 10)
        self.assertEqual(metrics["worker_entered_to_provider_dispatching_ms"], 185)
        self.assertEqual(metrics["session_lock_wait_ms"], 20)
        self.assertEqual(metrics["app_reference_materialize_ms"], 60)
        self.assertEqual(metrics["provider_input_build_ms"], 15)
        self.assertEqual(metrics["app_reference_count"], 2)
        self.assertEqual(metrics["storage_reference_count"], 1)
        self.assertEqual(metrics["materialized_reference_count"], 1)
        self.assertEqual(metrics["attachment_count"], 1)
        self.assertEqual(metrics["reference_cache_hit"], 0)
        cohort_metrics = report["cohorts"]["codex_warm"]["metrics"]
        self.assertEqual(cohort_metrics["app_reference_count"]["p50"], 2)
        self.assertEqual(cohort_metrics["reference_cache_hit"]["true_rate"], 0.0)

    def test_reads_history_and_deduplicates_tail_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-history", runtime_mode="agentic", provider_id="codex")
            events = _turn_events("sess-history", "turn-1", BASE, provider_id="codex")
            _write_events(root, "default", "sess-history", events[-2:])
            _write_events(root, "default", "sess-history", events, history=True)

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0, include_turns=True)

        self.assertEqual(report["summary"]["events_loaded"], 7)
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

    def test_associates_completed_session_prewarm_with_next_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-prewarm", runtime_mode="agentic", provider_id="codex")
            _write_events(
                root,
                "default",
                "sess-prewarm",
                [
                    _event(
                        "prewarm-completed",
                        "default",
                        "sess-prewarm",
                        None,
                        "runtime.prewarm.completed",
                        BASE - timedelta(seconds=1),
                        {"provider_id": "codex", "prewarm_total_ms": 321.5, "status": "completed"},
                    ),
                    *_turn_events(
                        "sess-prewarm",
                        "turn-after-prewarm",
                        BASE,
                        provider_id="codex",
                        ensure_runtime_ms=0.05,
                        ensure_provider_thread_ms=0.01,
                    ),
                ],
            )

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0, include_turns=True)

        self.assertEqual(report["summary"]["turns_reported"], 1)
        metrics = report["turns"][0]["metrics"]
        self.assertEqual(metrics["prewarm_wait_ms"], 0)
        self.assertEqual(metrics["prewarm_total_ms"], 321.5)

    def test_does_not_reuse_completed_session_prewarm_already_reported_by_turn_wait(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "maverick"
            _write_session(root, "default", "sess-prewarm", runtime_mode="agentic", provider_id="codex")
            _write_events(
                root,
                "default",
                "sess-prewarm",
                [
                    *_turn_events(
                        "sess-prewarm",
                        "turn-waited",
                        BASE,
                        provider_id="codex",
                        prewarm_wait_ms=50,
                        prewarm_total_ms=200,
                    ),
                    _event(
                        "prewarm-completed",
                        "default",
                        "sess-prewarm",
                        None,
                        "runtime.prewarm.completed",
                        BASE + timedelta(milliseconds=190),
                        {"provider_id": "codex", "prewarm_total_ms": 200, "status": "completed"},
                    ),
                    *_turn_events("sess-prewarm", "turn-later", BASE + timedelta(minutes=1), provider_id="codex"),
                ],
            )

            report = runtime_turn_latency_report.build_report(root, workspaces={"default"}, limit_turns=0, include_turns=True)

        later_metrics = next(item for item in report["turns"] if item["turn_id"] == "turn-later")["metrics"]
        self.assertNotIn("prewarm_total_ms", later_metrics)


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
    prewarm_wait_ms: float | None = None,
    prewarm_total_ms: float | None = None,
) -> list[dict[str, object]]:
    workspace_id = "default"
    queued_at = start
    receive_metric_at = start + timedelta(milliseconds=50)
    post_queue_at = start + timedelta(milliseconds=60)
    worker_at = start + timedelta(milliseconds=200)
    dispatch_at = start + timedelta(milliseconds=450)
    sent_at = start + timedelta(milliseconds=760)
    accepted_at = start + timedelta(milliseconds=780)
    dispatch_payload: dict[str, object] = {"provider_id": provider_id, "runtime_mode": runtime_mode}
    if include_launch_metrics:
        dispatch_payload.update(
            {
                "launch_spec_ms": 25,
                "skill_resolve_ms": 5,
                "skill_prepare_ms": 15,
            }
        )
    events = [
        _event("queued", workspace_id, session_id, turn_id, "runtime.turn.queued", queued_at, {"provider_id": provider_id}),
        _event(
            "receive",
            workspace_id,
            session_id,
            turn_id,
            "runtime.turn.receive_to_queued",
            receive_metric_at,
            {
                "receive_to_queued_ms": 50,
                "claim_ms": 1,
                "session_create_ms": 2,
                "reference_validate_ms": 3,
                "queue_turn_ms": 4,
            },
        ),
        _event(
            "post-queue",
            workspace_id,
            session_id,
            turn_id,
            "runtime.turn.post_queue_response",
            post_queue_at,
            {"post_queue_response_ms": 10},
        ),
    ]
    if prewarm_wait_ms is not None:
        prewarm_payload: dict[str, object] = {
            "provider_id": provider_id,
            "prewarm_wait_ms": prewarm_wait_ms,
            "completed": True,
            "timed_out": False,
        }
        if prewarm_total_ms is not None:
            prewarm_payload["prewarm_total_ms"] = prewarm_total_ms
        events.append(
            _event(
                "prewarm-waited",
                workspace_id,
                session_id,
                turn_id,
                "runtime.turn.prewarm_waited",
                start + timedelta(milliseconds=180),
                prewarm_payload,
            )
        )
    events.extend(
        [
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
    )
    return events


def _event(
    prefix: str,
    workspace_id: str,
    session_id: str,
    turn_id: str | None,
    event_type: str,
    created_at: datetime,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "event_id": f"{turn_id or 'session'}-{prefix}",
        "workspace_id": workspace_id,
        "session_id": session_id,
        "plane": "turn" if turn_id is not None else "runtime",
        "event_type": event_type,
        "turn_id": turn_id,
        "process_id": None,
        "payload": payload,
        "created_at": {runtime_turn_latency_report.DATETIME_MARKER: created_at.isoformat()},
    }


if __name__ == "__main__":
    unittest.main()
