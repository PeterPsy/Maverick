#!/usr/bin/env python3
"""Verify the G3 A-ACP evidence and the selected generic bridge contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
EVIDENCE_PATH = HERE / "opendesign_runtime_bridge_spike_0_16_1.json"
TERMINAL_EVENTS = {
    "runtime.turn.completed": "succeeded",
    "runtime.turn.failed": "failed",
    "runtime.turn.cancelled": "canceled",
}


class ProofError(RuntimeError):
    """Raised when the frozen G3 evidence no longer proves the decision."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofError(message)


def load_evidence(path: Path = EVIDENCE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), "G3 evidence must be a JSON object")
    return payload


def verify_decision(evidence: dict[str, Any]) -> None:
    _require(evidence.get("gate") == "G3", "unexpected gate")
    option_a = evidence.get("option_a_acp")
    _require(isinstance(option_a, dict), "missing A-ACP evidence")
    _require(option_a.get("attempted_first") is True, "A-ACP was not attempted first")
    _require(option_a.get("decision") == "rejected", "A-ACP must remain rejected")
    _require(evidence.get("selection") == "B", "G3 must select option B")

    criteria = option_a.get("criteria")
    _require(isinstance(criteria, dict), "missing A-ACP criteria")
    required = {
        "real_ui_create_run",
        "sse_before_terminal",
        "project_file_write",
        "full_correlation",
        "bidirectional_idempotent_cancel",
        "timeout",
        "backend_restart",
        "no_provider_secret",
        "actor_attribution",
        "terminal_result_packages",
        "resume",
        "run_scoped_capability",
    }
    _require(set(criteria) == required, "A-ACP criterion set drifted")
    for name in required:
        record = criteria[name]
        _require(record.get("result") in {"pass", "fail"}, f"criterion {name} lacks a result")
        _require(bool(str(record.get("evidence") or "").strip()), f"criterion {name} lacks evidence")
    for disqualifier in (
        "full_correlation",
        "backend_restart",
        "actor_attribution",
        "resume",
        "run_scoped_capability",
    ):
        _require(criteria[disqualifier]["result"] == "fail", f"{disqualifier} must disqualify A")

    contract = evidence.get("generic_core_contract")
    _require(isinstance(contract, dict), "missing generic core contract")
    serialized_contract = json.dumps(contract, sort_keys=True).lower()
    for forbidden in ("opendesign", "open_design", "od_project", "od_run", "design-studio"):
        _require(forbidden not in serialized_contract, f"app-specific name leaked into core contract: {forbidden}")
    _require(
        set(contract.get("operations") or [])
        == {"submit", "read_after_sequence", "interrupt", "inspect", "recover"},
        "generic operation set drifted",
    )
    translation = evidence.get("app_owned_translation")
    _require(isinstance(translation, dict), "missing app-owned translation")
    _require(
        set(translation.get("correlation") or [])
        == {"workspace_id", "od_project_id", "od_run_id", "runtime_session_id", "turn_id"},
        "correlation tuple is incomplete",
    )
    _require(
        set(translation.get("terminal_packages") or []) == {"succeeded", "failed", "canceled"},
        "terminal package set is incomplete",
    )


def verify_upstream(evidence: dict[str, Any], upstream_root: Path) -> None:
    upstream_root = upstream_root.resolve()
    _require((upstream_root / ".git").exists(), "upstream root is not a git checkout")
    head = subprocess.run(
        ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _require(head == evidence["upstream"]["commit"], f"upstream commit mismatch: {head}")
    for relative, expected in evidence["upstream"]["source_files"].items():
        actual = _sha256(upstream_root / relative)
        _require(actual == expected, f"upstream source digest mismatch: {relative}")

    local_profiles = (upstream_root / "apps/daemon/src/runtimes/local-profiles.ts").read_text(encoding="utf-8")
    trace_env = (upstream_root / "apps/daemon/src/runtimes/env.ts").read_text(encoding="utf-8")
    kimi = (upstream_root / "apps/daemon/src/runtimes/defs/kimi.ts").read_text(encoding="utf-8")
    params = (upstream_root / "apps/daemon/src/agent-protocol/acp/session-params.ts").read_text(encoding="utf-8")
    session = (upstream_root / "apps/daemon/src/agent-protocol/acp/session.ts").read_text(encoding="utf-8")
    _require("...baseWithoutAuthProbe" in local_profiles, "local profiles no longer inherit a base adapter")
    _require("...base.buildArgs(" in local_profiles, "local profiles no longer inherit base arguments")
    _require("streamFormat" not in local_profiles, "local profiles unexpectedly gained an independent protocol")
    _require("agentId !== 'amr'" in trace_env, "run trace env is no longer AMR-only")
    _require("OPEN_DESIGN_RUN_ID" in trace_env, "expected upstream trace identifier is missing")
    _require("resumesSessionViaAcpLoad" not in kimi, "Kimi unexpectedly gained ACP load resume")
    _require("buildArgs: () => ['acp']" in kimi, "Kimi ACP launch contract drifted")
    _require("mcpServers" in params and "runId" not in params, "ACP session/new identity shape drifted")
    _require("'session/load'" in session, "ACP resume transport is missing")
    _require("'session/cancel'" in session, "ACP cancel transport is missing")
    _require("resumeSessionId" in session, "ACP resume controller is missing")


class _GenericStreamProbe:
    """Tiny durable model of the app-agnostic primitive selected by G3."""

    def __init__(self, journal_path: Path):
        self.journal_path = journal_path
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.journal_path.exists():
            return {"requests": {}, "streams": {}}
        return json.loads(self.journal_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        temp = self.journal_path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.journal_path)

    @staticmethod
    def _stable(prefix: str, *parts: str) -> str:
        value = "\0".join(parts).encode("utf-8")
        return f"{prefix}_{hashlib.sha256(value).hexdigest()[:20]}"

    def submit(self, *, workspace_id: str, source_app_id: str, actor_id: str, idempotency_key: str) -> dict[str, str]:
        request_key = "\0".join((workspace_id, source_app_id, idempotency_key))
        existing = self.state["requests"].get(request_key)
        if existing:
            return dict(existing)
        stream_id = self._stable("stream", workspace_id, source_app_id, idempotency_key)
        record = {
            "request_id": self._stable("request", request_key),
            "stream_id": stream_id,
            "runtime_session_id": self._stable("session", request_key),
            "turn_id": self._stable("turn", request_key),
            "status": "submitted",
        }
        self.state["requests"][request_key] = record
        self.state["streams"][stream_id] = {
            "workspace_id": workspace_id,
            "source_app_id": source_app_id,
            "actor_id": actor_id,
            "events": [],
            "terminal": None,
        }
        self.emit(
            stream_id,
            workspace_id=workspace_id,
            source_app_id=source_app_id,
            event_type="runtime.turn.queued",
            payload={},
        )
        return dict(record)

    def emit(
        self,
        stream_id: str,
        *,
        workspace_id: str,
        source_app_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        stream = self._owned(stream_id, workspace_id, source_app_id)
        terminal_status = TERMINAL_EVENTS.get(event_type)
        if stream["terminal"] is not None:
            raise ProofError("cannot append after terminal")
        sequence = len(stream["events"]) + 1
        event = {
            "stream_id": stream_id,
            "sequence": sequence,
            "event_id": self._stable("event", stream_id, str(sequence)),
            "event_type": event_type,
            "timestamp": f"proof-{sequence}",
            "payload": payload,
            "terminal": terminal_status is not None,
        }
        stream["events"].append(event)
        if terminal_status is not None:
            stream["terminal"] = terminal_status
        self._save()
        return dict(event)

    def read_after_sequence(
        self,
        stream_id: str,
        *,
        workspace_id: str,
        source_app_id: str,
        after_sequence: int,
    ) -> list[dict[str, Any]]:
        stream = self._owned(stream_id, workspace_id, source_app_id)
        return [dict(event) for event in stream["events"] if event["sequence"] > after_sequence]

    def interrupt(self, stream_id: str, *, workspace_id: str, source_app_id: str) -> dict[str, Any]:
        stream = self._owned(stream_id, workspace_id, source_app_id)
        if stream["terminal"] is not None:
            return {"status": stream["terminal"], "interrupted": False}
        self.emit(
            stream_id,
            workspace_id=workspace_id,
            source_app_id=source_app_id,
            event_type="runtime.turn.cancelled",
            payload={"reason": "app_interrupt"},
        )
        return {"status": "canceled", "interrupted": True}

    def _owned(self, stream_id: str, workspace_id: str, source_app_id: str) -> dict[str, Any]:
        stream = self.state["streams"].get(stream_id)
        if not stream or stream["workspace_id"] != workspace_id or stream["source_app_id"] != source_app_id:
            raise PermissionError("stream ownership mismatch")
        return stream


def run_selected_b_contract_proof() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="maverick-g3-b-") as temp_dir:
        journal = Path(temp_dir) / "stream-journal.json"
        broker = _GenericStreamProbe(journal)
        submitted = broker.submit(
            workspace_id="workspace-a",
            source_app_id="app-a",
            actor_id="actor-a",
            idempotency_key="request-a",
        )
        retry = broker.submit(
            workspace_id="workspace-a",
            source_app_id="app-a",
            actor_id="actor-a",
            idempotency_key="request-a",
        )
        _require(retry == submitted, "submission retry was not idempotent")
        stream_id = submitted["stream_id"]
        broker.emit(
            stream_id,
            workspace_id="workspace-a",
            source_app_id="app-a",
            event_type="runtime.turn.started",
            payload={},
        )
        broker.emit(
            stream_id,
            workspace_id="workspace-a",
            source_app_id="app-a",
            event_type="runtime.output.delta",
            payload={"text": "early"},
        )
        broker.emit(
            stream_id,
            workspace_id="workspace-a",
            source_app_id="app-a",
            event_type="runtime.file.changed",
            payload={"relative_path": "index.html"},
        )
        before_restart = broker.read_after_sequence(
            stream_id,
            workspace_id="workspace-a",
            source_app_id="app-a",
            after_sequence=0,
        )
        _require(not before_restart[-1]["terminal"], "stream terminated before incremental output")
        try:
            broker.read_after_sequence(
                stream_id,
                workspace_id="workspace-b",
                source_app_id="app-a",
                after_sequence=0,
            )
        except PermissionError:
            pass
        else:
            raise ProofError("cross-workspace stream read was allowed")

        recovered = _GenericStreamProbe(journal)
        after_restart = recovered.read_after_sequence(
            stream_id,
            workspace_id="workspace-a",
            source_app_id="app-a",
            after_sequence=2,
        )
        _require([event["sequence"] for event in after_restart] == [3, 4], "restart resume sequence drifted")
        first_cancel = recovered.interrupt(stream_id, workspace_id="workspace-a", source_app_id="app-a")
        second_cancel = recovered.interrupt(stream_id, workspace_id="workspace-a", source_app_id="app-a")
        _require(first_cancel["interrupted"] is True, "first interrupt did not transition")
        _require(second_cancel == {"status": "canceled", "interrupted": False}, "interrupt was not idempotent")
        events = recovered.read_after_sequence(
            stream_id,
            workspace_id="workspace-a",
            source_app_id="app-a",
            after_sequence=0,
        )
        _require(sum(event["event_type"] == "runtime.turn.cancelled" for event in events) == 1, "duplicate cancel terminal")
        _require(events[-1]["terminal"] is True, "terminal event missing")
        raw = journal.read_text(encoding="utf-8").lower()
        for forbidden in ("api_key", "access_token", "cookie", "bearer"):
            _require(forbidden not in raw, f"credential marker persisted: {forbidden}")
        return {
            "idempotent_submit": True,
            "incremental_before_terminal": True,
            "file_event": True,
            "restart_resume_after_sequence": True,
            "cross_workspace_denied": True,
            "idempotent_interrupt": True,
            "terminal_status": "canceled",
            "secret_markers_absent": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", type=Path)
    args = parser.parse_args()
    evidence = load_evidence()
    verify_decision(evidence)
    if args.upstream_root is not None:
        verify_upstream(evidence, args.upstream_root)
    result = {
        "gate": "G3",
        "selection": evidence["selection"],
        "decision": "verified",
        "upstream_verified": args.upstream_root is not None,
        "selected_b_contract": run_selected_b_contract_proof(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
