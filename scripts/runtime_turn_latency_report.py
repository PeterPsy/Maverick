#!/usr/bin/env python3
"""Aggregate runtime turn latency spans from persisted Maverick events."""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import fcntl
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterator


DATETIME_MARKER = "__maverick_datetime__"
INTERESTING_EVENT_TYPES = {
    "runtime.turn.queued",
    "runtime.turn.receive_to_queued",
    "runtime.turn.post_queue_response",
    "runtime.turn.prewarm_waited",
    "runtime.turn.worker_started",
    "runtime.provider.dispatching",
    "runtime.provider.turn_start_sent",
    "runtime.provider.accepted",
}
EVENT_KEYS = {
    "runtime.turn.queued": "queued",
    "runtime.turn.receive_to_queued": "receive_to_queued",
    "runtime.turn.post_queue_response": "post_queue_response",
    "runtime.turn.prewarm_waited": "prewarm_waited",
    "runtime.turn.worker_started": "worker_started",
    "runtime.provider.dispatching": "provider_dispatching",
    "runtime.provider.turn_start_sent": "turn_start_sent",
    "runtime.provider.accepted": "provider_accepted",
}
METRIC_NAMES = (
    "receive_to_queued_ms",
    "claim_ms",
    "session_create_ms",
    "reference_validate_ms",
    "queue_turn_ms",
    "post_queue_response_ms",
    "prewarm_wait_ms",
    "prewarm_total_ms",
    "queued_to_worker_started_ms",
    "worker_started_to_provider_dispatching_ms",
    "worker_started_to_turn_start_sent_ms",
    "provider_dispatching_to_turn_start_sent_ms",
    "launch_spec_ms",
    "skill_resolve_ms",
    "skill_prepare_ms",
    "ensure_runtime_ms",
    "ensure_provider_thread_ms",
    "turn_start_sent_to_provider_accepted_ms",
    "queued_to_provider_accepted_ms",
    "receive_to_provider_accepted_ms",
    "first_turn_receive_to_provider_accepted_ms",
)
COHORT_NAMES = ("codex_cold", "codex_warm", "plain_hosted", "other_provider")
CODEX_PROVIDER_ID = "codex"
HOSTED_TEXT_RUNTIME_PROVIDER_ID = "hosted-text-runtime"
SLO_SCOPE_BY_COHORT = {
    "codex_cold": "codex_runtime_cold",
    "codex_warm": "codex_runtime_warm",
    "plain_hosted": "hosted_http_provider",
    "other_provider": "other_provider",
}


@dataclass(frozen=True)
class RuntimeEventSnapshot:
    event_id: str
    workspace_id: str
    session_id: str
    turn_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class SessionSnapshot:
    workspace_id: str
    session_id: str
    runtime_mode: str | None = None
    provider_id: str | None = None


@dataclass
class TurnEvents:
    workspace_id: str
    session_id: str
    turn_id: str
    events: dict[str, RuntimeEventSnapshot] = field(default_factory=dict)

    def add(self, event: RuntimeEventSnapshot) -> None:
        key = EVENT_KEYS.get(event.event_type)
        if key is None:
            return
        current = self.events.get(key)
        if current is None or _event_sort_key(event) < _event_sort_key(current):
            self.events[key] = event


@dataclass(frozen=True)
class TurnObservation:
    workspace_id: str
    session_id: str
    turn_id: str
    cohort: str
    provider_id: str | None
    runtime_mode: str | None
    anchor_at: datetime
    metrics: dict[str, float]


@dataclass
class LoadStats:
    session_count: int = 0
    event_count: int = 0
    duplicate_event_count: int = 0
    warning_messages: list[str] = field(default_factory=list)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    since = _parse_since(args.since) if args.since else None
    report = build_report(
        args.repository_root.resolve(),
        workspaces=set(args.workspace or []),
        since=since,
        limit_turns=args.limit_turns,
        include_turns=args.include_turns,
        codex_cold_threshold_ms=args.codex_cold_threshold_ms,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human_report(report)
    return 0


def build_report(
    repository_root: Path,
    *,
    workspaces: set[str] | None = None,
    since: datetime | None = None,
    limit_turns: int | None = 200,
    include_turns: bool = False,
    codex_cold_threshold_ms: float = 50.0,
) -> dict[str, Any]:
    sessions, events, load_stats = load_runtime_snapshots(repository_root, workspaces=workspaces or set())
    all_observations = _build_observations(sessions, events, codex_cold_threshold_ms=codex_cold_threshold_ms)
    filtered = [observation for observation in all_observations if since is None or observation.anchor_at >= since]
    filtered.sort(key=lambda item: (item.anchor_at, item.session_id, item.turn_id))
    if limit_turns is not None and limit_turns > 0:
        filtered = filtered[-limit_turns:]

    cohorts = {
        cohort_name: _summarize_cohort(cohort_name, [item for item in filtered if item.cohort == cohort_name])
        for cohort_name in COHORT_NAMES
    }
    report: dict[str, Any] = {
        "repository_root": str(repository_root),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "filters": {
            "workspaces": sorted(workspaces or []),
            "since": since.isoformat() if since is not None else None,
            "limit_turns": limit_turns,
            "codex_cold_threshold_ms": codex_cold_threshold_ms,
        },
        "summary": {
            "sessions_loaded": load_stats.session_count,
            "events_loaded": load_stats.event_count,
            "duplicate_events_skipped": load_stats.duplicate_event_count,
            "turns_observed": len(all_observations),
            "turns_reported": len(filtered),
            "warnings": load_stats.warning_messages,
        },
        "cohorts": cohorts,
        "notes": [
            "codex_cold uses ensure_runtime_ms or ensure_provider_thread_ms at/above the configured threshold when those spans exist; otherwise it falls back to the first observed Codex provider turn in a session.",
            (
                "plain_hosted has slo_scope=hosted_http_provider because provider acceptance can include "
                "external hosted HTTP network latency."
            ),
            "receive_to_provider_accepted_ms is reconstructed as receive_to_queued_ms plus queued_to_provider_accepted_ms when both components are available.",
            "first_turn_receive_to_provider_accepted_ms is populated only for the first observed provider turn in each session.",
            "prewarm_wait_ms and prewarm_total_ms come from runtime.turn.prewarm_waited and measure user-visible wait before execution, not provider-internal ensure spans.",
            "claim_ms, session_create_ms, reference_validate_ms, queue_turn_ms, and post_queue_response_ms are emitted only by newer runtime submission paths.",
            "The report intentionally omits input text and provider payload bodies beyond numeric latency spans.",
        ],
    }
    if include_turns:
        report["turns"] = [_turn_payload(item) for item in filtered]
    return report


def load_runtime_snapshots(
    repository_root: Path,
    *,
    workspaces: set[str],
) -> tuple[dict[tuple[str, str], SessionSnapshot], list[RuntimeEventSnapshot], LoadStats]:
    stats = LoadStats()
    sessions: dict[tuple[str, str], SessionSnapshot] = {}
    events_by_id: dict[str, RuntimeEventSnapshot] = {}
    for session_root in _session_roots(repository_root, workspaces=workspaces):
        workspace_id = _workspace_id_from_session_root(repository_root, session_root)
        session_id = session_root.name
        session = _load_session_snapshot(session_root, workspace_id=workspace_id, fallback_session_id=session_id, stats=stats)
        sessions[(session.workspace_id, session.session_id)] = session
        stats.session_count += 1
        for event_path in _event_paths(session_root):
            for event in _load_event_snapshots(event_path, stats=stats):
                if event.event_type not in INTERESTING_EVENT_TYPES:
                    continue
                if event.event_id in events_by_id:
                    stats.duplicate_event_count += 1
                    continue
                events_by_id[event.event_id] = event
                stats.event_count += 1
    events = sorted(events_by_id.values(), key=_event_sort_key)
    return sessions, events, stats


def print_human_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    filters = report["filters"]
    print("Runtime turn latency baseline")
    print(f"Repository: {report['repository_root']}")
    workspace_label = ", ".join(filters["workspaces"]) if filters["workspaces"] else "all"
    print(f"Workspaces: {workspace_label}")
    print(f"Since: {filters['since'] or 'beginning'}")
    print(f"Turn limit: {filters['limit_turns'] or 'none'}")
    print(f"Codex cold threshold: {filters['codex_cold_threshold_ms']}ms")
    print(
        "Loaded: "
        f"{summary['sessions_loaded']} sessions, "
        f"{summary['events_loaded']} events, "
        f"{summary['duplicate_events_skipped']} duplicate events skipped"
    )
    print(f"Turns: {summary['turns_reported']} reported from {summary['turns_observed']} observed")
    if summary["warnings"]:
        print(f"Warnings: {len(summary['warnings'])}")
        for warning in summary["warnings"][:5]:
            print(f"  {warning}")
        if len(summary["warnings"]) > 5:
            print(f"  ... {len(summary['warnings']) - 5} more")

    for cohort_name in COHORT_NAMES:
        cohort = report["cohorts"][cohort_name]
        print("")
        print(
            f"{cohort_name}: {cohort['turn_count']} turns across "
            f"{cohort['session_count']} sessions (slo_scope={cohort['slo_scope']})"
        )
        for metric_name in METRIC_NAMES:
            metric = cohort["metrics"].get(metric_name)
            if not metric:
                continue
            print(
                f"  {metric_name}: "
                f"n={metric['count']} "
                f"p50={metric['p50_ms']}ms "
                f"p95={metric['p95_ms']}ms "
                f"min={metric['min_ms']}ms "
                f"max={metric['max_ms']}ms"
            )
    print("")
    print("Notes:")
    for note in report["notes"]:
        print(f"  {note}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Maverick repository root. Defaults to the parent of scripts/.",
    )
    parser.add_argument(
        "--workspace",
        action="append",
        help="Workspace id to include. May be provided more than once. Defaults to all workspaces.",
    )
    parser.add_argument(
        "--since",
        help="Only report turns whose latest lifecycle event is at or after this ISO timestamp or relative value like 24h, 7d, 30m.",
    )
    parser.add_argument(
        "--limit-turns",
        type=int,
        default=200,
        help="Maximum number of most recent turn observations to include after filtering. Use 0 for no limit.",
    )
    parser.add_argument(
        "--codex-cold-threshold-ms",
        type=float,
        default=50.0,
        help="Classify Codex turns as cold when ensure_runtime_ms or ensure_provider_thread_ms is at or above this threshold.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--include-turns", action="store_true", help="Include per-turn metric rows in JSON output.")
    args = parser.parse_args(argv)
    if args.limit_turns < 0:
        parser.error("--limit-turns must be zero or positive")
    if args.codex_cold_threshold_ms < 0:
        parser.error("--codex-cold-threshold-ms must be zero or positive")
    return args


def _session_roots(repository_root: Path, *, workspaces: set[str]) -> list[Path]:
    workspace_roots: list[Path]
    if workspaces:
        workspace_roots = [repository_root / "workspaces" / workspace_id for workspace_id in sorted(workspaces)]
    else:
        workspace_roots = sorted(path for path in (repository_root / "workspaces").glob("*") if path.is_dir())
    roots: list[Path] = []
    for workspace_root in workspace_roots:
        sessions_root = workspace_root / "runtime" / "sessions"
        if sessions_root.is_dir():
            roots.extend(path for path in sessions_root.glob("*") if path.is_dir())
    return sorted(roots)


def _workspace_id_from_session_root(repository_root: Path, session_root: Path) -> str:
    try:
        relative = session_root.relative_to(repository_root)
    except ValueError:
        return ""
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == "workspaces":
        return parts[1]
    return ""


def _event_paths(session_root: Path) -> list[Path]:
    paths: list[Path] = []
    history_root = session_root / "events-history"
    if history_root.is_dir():
        paths.extend(sorted(path for path in history_root.glob("*.json") if path.stem.isdigit()))
    legacy_history = session_root / "events-history.json"
    if legacy_history.is_file():
        paths.append(legacy_history)
    tail = session_root / "events.json"
    if tail.is_file():
        paths.append(tail)
    return paths


def _load_session_snapshot(
    session_root: Path,
    *,
    workspace_id: str,
    fallback_session_id: str,
    stats: LoadStats,
) -> SessionSnapshot:
    documents = _read_json_collection(session_root / "session.json", stats=stats)
    document = documents[0] if documents else {}
    return SessionSnapshot(
        workspace_id=str(document.get("workspace_id") or workspace_id),
        session_id=str(document.get("session_id") or fallback_session_id),
        runtime_mode=_optional_str(document.get("runtime_mode")),
        provider_id=_optional_str(document.get("provider_id")),
    )


def _load_event_snapshots(path: Path, *, stats: LoadStats) -> list[RuntimeEventSnapshot]:
    snapshots: list[RuntimeEventSnapshot] = []
    for document in _read_json_collection(path, stats=stats):
        snapshot = _event_snapshot(document)
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def _read_json_collection(path: Path, *, stats: LoadStats) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        with _maybe_shared_collection_lock(path):
            payload = json.loads(path.read_text(encoding="utf-8"), object_hook=_decode_document_value)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        stats.warning_messages.append(f"skipped unreadable JSON collection {path}: {error}")
        return []
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        stats.warning_messages.append(f"skipped non-document JSON collection {path}")
        return []
    return payload


@contextmanager
def _maybe_shared_collection_lock(path: Path) -> Iterator[None]:
    lock_path = _lock_path_for_collection(path)
    if not lock_path.is_file():
        with nullcontext():
            yield
        return
    with lock_path.open("rb") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _lock_path_for_collection(path: Path) -> Path:
    if path.parent.name == "events-history" and path.stem.isdigit():
        return path.parent.with_suffix(".lock")
    return path.with_suffix(f"{path.suffix}.lock")


def _event_snapshot(document: dict[str, Any]) -> RuntimeEventSnapshot | None:
    event_id = _optional_str(document.get("event_id"))
    session_id = _optional_str(document.get("session_id"))
    turn_id = _optional_str(document.get("turn_id"))
    event_type = _optional_str(document.get("event_type"))
    created_at = _coerce_datetime(document.get("created_at"))
    if not event_id or not session_id or not turn_id or not event_type or created_at is None:
        return None
    payload = document.get("payload")
    return RuntimeEventSnapshot(
        event_id=event_id,
        workspace_id=_optional_str(document.get("workspace_id")) or "",
        session_id=session_id,
        turn_id=turn_id,
        event_type=event_type,
        payload=payload if isinstance(payload, dict) else {},
        created_at=created_at,
    )


def _build_observations(
    sessions: dict[tuple[str, str], SessionSnapshot],
    events: list[RuntimeEventSnapshot],
    *,
    codex_cold_threshold_ms: float,
) -> list[TurnObservation]:
    sessions_by_id = {session.session_id: session for session in sessions.values()}
    grouped: dict[tuple[str, str, str], TurnEvents] = {}
    for event in events:
        key = (event.workspace_id, event.session_id, event.turn_id)
        group = grouped.setdefault(
            key,
            TurnEvents(workspace_id=event.workspace_id, session_id=event.session_id, turn_id=event.turn_id),
        )
        group.add(event)

    preliminary: list[tuple[TurnEvents, dict[str, float], str | None, str | None, datetime]] = []
    for group in grouped.values():
        metrics = _turn_metrics(group)
        if not metrics:
            continue
        session = sessions.get((group.workspace_id, group.session_id)) or sessions_by_id.get(group.session_id)
        provider_id = _provider_id_for_turn(group, session)
        runtime_mode = _runtime_mode_for_turn(group, session)
        anchor_at = max(event.created_at for event in group.events.values())
        preliminary.append((group, metrics, provider_id, runtime_mode, anchor_at))

    first_codex_by_session: dict[tuple[str, str], tuple[datetime, str]] = {}
    for group, _metrics, provider_id, runtime_mode, anchor_at in preliminary:
        if not _is_codex_turn(provider_id=provider_id, runtime_mode=runtime_mode):
            continue
        session_key = (group.workspace_id, group.session_id)
        current = first_codex_by_session.get(session_key)
        sort_value = (anchor_at, group.turn_id)
        if current is None or sort_value < current:
            first_codex_by_session[session_key] = sort_value

    first_turn_by_session: dict[tuple[str, str], tuple[datetime, str]] = {}
    for group, _metrics, _provider_id, _runtime_mode, anchor_at in preliminary:
        session_key = (group.workspace_id, group.session_id)
        current = first_turn_by_session.get(session_key)
        sort_value = _turn_order_sort_value(group, fallback_at=anchor_at)
        if current is None or sort_value < current:
            first_turn_by_session[session_key] = sort_value

    observations: list[TurnObservation] = []
    for group, metrics, provider_id, runtime_mode, anchor_at in preliminary:
        if first_turn_by_session.get((group.workspace_id, group.session_id)) == _turn_order_sort_value(group, fallback_at=anchor_at):
            first_turn_e2e = metrics.get("receive_to_provider_accepted_ms")
            if first_turn_e2e is not None:
                metrics = {**metrics, "first_turn_receive_to_provider_accepted_ms": first_turn_e2e}
        cohort = _cohort_for_turn(
            group,
            metrics=metrics,
            provider_id=provider_id,
            runtime_mode=runtime_mode,
            first_codex_by_session=first_codex_by_session,
            anchor_at=anchor_at,
            codex_cold_threshold_ms=codex_cold_threshold_ms,
        )
        observations.append(
            TurnObservation(
                workspace_id=group.workspace_id,
                session_id=group.session_id,
                turn_id=group.turn_id,
                cohort=cohort,
                provider_id=provider_id,
                runtime_mode=runtime_mode,
                anchor_at=anchor_at,
                metrics=metrics,
            )
        )
    return sorted(observations, key=lambda item: (item.anchor_at, item.session_id, item.turn_id))


def _turn_metrics(group: TurnEvents) -> dict[str, float]:
    events = group.events
    metrics: dict[str, float] = {}
    receive = events.get("receive_to_queued")
    post_queue_response = events.get("post_queue_response")
    prewarm_waited = events.get("prewarm_waited")
    queued = events.get("queued")
    worker = events.get("worker_started")
    dispatching = events.get("provider_dispatching")
    sent = events.get("turn_start_sent")
    accepted = events.get("provider_accepted")

    if receive is not None:
        _set_metric(metrics, "receive_to_queued_ms", _numeric(receive.payload.get("receive_to_queued_ms")))
        for key in ("claim_ms", "session_create_ms", "reference_validate_ms", "queue_turn_ms"):
            _set_metric(metrics, key, _numeric(receive.payload.get(key)))
    if post_queue_response is not None:
        _set_metric(metrics, "post_queue_response_ms", _numeric(post_queue_response.payload.get("post_queue_response_ms")))
    if prewarm_waited is not None:
        _set_metric(metrics, "prewarm_wait_ms", _numeric(prewarm_waited.payload.get("prewarm_wait_ms")))
        _set_metric(metrics, "prewarm_total_ms", _numeric(prewarm_waited.payload.get("prewarm_total_ms")))
    _set_metric(metrics, "queued_to_worker_started_ms", _delta_ms(queued, worker))
    _set_metric(metrics, "worker_started_to_provider_dispatching_ms", _delta_ms(worker, dispatching))
    _set_metric(metrics, "worker_started_to_turn_start_sent_ms", _delta_ms(worker, sent))
    _set_metric(metrics, "provider_dispatching_to_turn_start_sent_ms", _delta_ms(dispatching, sent))
    if dispatching is not None:
        for key in ("launch_spec_ms", "skill_resolve_ms", "skill_prepare_ms"):
            _set_metric(metrics, key, _numeric(dispatching.payload.get(key)))
    ensure_source = sent or accepted
    if ensure_source is not None:
        for key in ("ensure_runtime_ms", "ensure_provider_thread_ms"):
            _set_metric(metrics, key, _numeric(ensure_source.payload.get(key)))
    ack_ms = _numeric(accepted.payload.get("turn_start_to_ack_ms")) if accepted is not None else None
    if ack_ms is None:
        ack_ms = _delta_ms(sent, accepted)
    _set_metric(metrics, "turn_start_sent_to_provider_accepted_ms", ack_ms)
    queued_to_accepted = _delta_ms(queued, accepted)
    _set_metric(metrics, "queued_to_provider_accepted_ms", queued_to_accepted)
    receive_to_queued = metrics.get("receive_to_queued_ms")
    if receive_to_queued is not None and queued_to_accepted is not None:
        _set_metric(metrics, "receive_to_provider_accepted_ms", receive_to_queued + queued_to_accepted)
    return metrics


def _turn_order_sort_value(group: TurnEvents, *, fallback_at: datetime) -> tuple[datetime, str]:
    queued = group.events.get("queued")
    if queued is not None:
        return queued.created_at, group.turn_id
    if group.events:
        return min(event.created_at for event in group.events.values()), group.turn_id
    return fallback_at, group.turn_id


def _provider_id_for_turn(group: TurnEvents, session: SessionSnapshot | None) -> str | None:
    for key in ("provider_accepted", "turn_start_sent", "provider_dispatching", "worker_started", "queued"):
        event = group.events.get(key)
        if event is None:
            continue
        provider_id = _optional_str(event.payload.get("provider_id"))
        if provider_id:
            return provider_id
    return session.provider_id if session is not None else None


def _runtime_mode_for_turn(group: TurnEvents, session: SessionSnapshot | None) -> str | None:
    for key in ("provider_accepted", "turn_start_sent", "provider_dispatching"):
        event = group.events.get(key)
        if event is None:
            continue
        runtime_mode = _optional_str(event.payload.get("runtime_mode"))
        if runtime_mode:
            return runtime_mode
    return session.runtime_mode if session is not None else None


def _cohort_for_turn(
    group: TurnEvents,
    *,
    metrics: dict[str, float],
    provider_id: str | None,
    runtime_mode: str | None,
    first_codex_by_session: dict[tuple[str, str], tuple[datetime, str]],
    anchor_at: datetime,
    codex_cold_threshold_ms: float,
) -> str:
    if runtime_mode == "plain_hosted_chat" or provider_id == HOSTED_TEXT_RUNTIME_PROVIDER_ID:
        return "plain_hosted"
    if _is_codex_turn(provider_id=provider_id, runtime_mode=runtime_mode):
        cold_signal = _codex_cold_signal(metrics, threshold_ms=codex_cold_threshold_ms)
        if cold_signal is not None:
            return "codex_cold" if cold_signal else "codex_warm"
        first = first_codex_by_session.get((group.workspace_id, group.session_id))
        return "codex_cold" if first == (anchor_at, group.turn_id) else "codex_warm"
    return "other_provider"


def _is_codex_turn(*, provider_id: str | None, runtime_mode: str | None) -> bool:
    return provider_id == CODEX_PROVIDER_ID and runtime_mode != "plain_hosted_chat"


def _codex_cold_signal(metrics: dict[str, float], *, threshold_ms: float) -> bool | None:
    values = [
        metrics.get("ensure_runtime_ms"),
        metrics.get("ensure_provider_thread_ms"),
    ]
    numeric_values = [value for value in values if isinstance(value, int | float)]
    if not numeric_values:
        return None
    return any(value >= threshold_ms for value in numeric_values)


def _summarize_cohort(cohort_name: str, observations: list[TurnObservation]) -> dict[str, Any]:
    metric_summaries = {}
    for metric_name in METRIC_NAMES:
        values = [item.metrics[metric_name] for item in observations if metric_name in item.metrics]
        if values:
            metric_summaries[metric_name] = _summarize_values(values)
    return {
        "slo_scope": SLO_SCOPE_BY_COHORT.get(cohort_name, cohort_name),
        "turn_count": len(observations),
        "session_count": len({(item.workspace_id, item.session_id) for item in observations}),
        "metrics": metric_summaries,
    }


def _summarize_values(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min_ms": _round_ms(ordered[0]),
        "p50_ms": _round_ms(_median(ordered)),
        "p95_ms": _round_ms(_nearest_rank_percentile(ordered, 95)),
        "max_ms": _round_ms(ordered[-1]),
    }


def _turn_payload(observation: TurnObservation) -> dict[str, Any]:
    return {
        "workspace_id": observation.workspace_id,
        "session_id": observation.session_id,
        "turn_id": observation.turn_id,
        "cohort": observation.cohort,
        "provider_id": observation.provider_id,
        "runtime_mode": observation.runtime_mode,
        "anchor_at": observation.anchor_at.isoformat(),
        "metrics": {key: _round_ms(value) for key, value in sorted(observation.metrics.items())},
    }


def _set_metric(metrics: dict[str, float], name: str, value: float | None) -> None:
    if value is None or not math.isfinite(value) or value < 0:
        return
    metrics[name] = value


def _delta_ms(start: RuntimeEventSnapshot | None, end: RuntimeEventSnapshot | None) -> float | None:
    if start is None or end is None:
        return None
    return (end.created_at - start.created_at).total_seconds() * 1000


def _numeric(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _median(values: list[float]) -> float:
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2


def _nearest_rank_percentile(values: list[float], percentile: int) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    index = max(0, min(len(values) - 1, math.ceil((percentile / 100) * len(values)) - 1))
    return values[index]


def _round_ms(value: float) -> float:
    return round(float(value), 3)


def _event_sort_key(event: RuntimeEventSnapshot) -> tuple[datetime, str]:
    return (event.created_at, event.event_id)


def _decode_document_value(value: dict[str, Any]) -> Any:
    timestamp = value.get(DATETIME_MARKER)
    if isinstance(timestamp, str) and len(value) == 1:
        parsed = _coerce_datetime(timestamp)
        return parsed if parsed is not None else value
    return value


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, dict):
        marker = value.get(DATETIME_MARKER)
        if isinstance(marker, str):
            return _coerce_datetime(marker)
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_since(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise SystemExit("--since cannot be empty")
    relative = _parse_relative_since(text)
    if relative is not None:
        return datetime.now(tz=UTC) - relative
    parsed = _coerce_datetime(text)
    if parsed is None:
        raise SystemExit("--since must be an ISO timestamp or a relative value like 24h, 7d, 30m")
    return parsed


def _parse_relative_since(value: str) -> timedelta | None:
    unit = value[-1:].lower()
    if unit not in {"m", "h", "d"}:
        return None
    try:
        amount = float(value[:-1])
    except ValueError:
        return None
    if amount < 0:
        return None
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


if __name__ == "__main__":
    sys.exit(main())
