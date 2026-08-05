"""App-owned OpenDesign translation and durable runtime correlation metadata."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any, Callable
from uuid import uuid4


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from opendesign_artifact import read_bundle_manifest  # noqa: E402
from opendesign_runtime import resolve_runtime_binding  # noqa: E402


BRIDGE_SCHEMA_VERSION = "1"
BRIDGE_DIRECTORY = "maverick-runtime"
CORRELATIONS_FILE = "correlations.json"
MAX_CORRELATIONS_BYTES = 8 * 1024 * 1024
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TERMINAL_STATUS = {"succeeded", "failed", "canceled"}
_GENERIC_EVENT_TYPES = {
    "runtime.turn.queued",
    "runtime.turn.started",
    "runtime.output.delta",
    "runtime.output.final",
    "runtime.file.changed",
    "runtime.turn.completed",
    "runtime.turn.failed",
    "runtime.turn.cancelled",
    "runtime.turn.timed-out",
}


class RuntimeBridgeError(RuntimeError):
    """Fail-closed app-owned translator or correlation error."""


def active_data_directory(payload: dict[str, Any]) -> Path:
    """Resolve only the verified bundle/data triple selected by G4 control."""
    app_data_root = _real_directory(Path(str(payload.get("data_root") or "")), label="Design Studio data root")
    generation_root = _real_directory(app_data_root / "opendesign", label="OpenDesign generation root")
    registry_root = _real_directory(SERVICE_ROOT / "vendor" / "open-design", label="OpenDesign registry root")
    manifest = read_bundle_manifest(SERVICE_ROOT / "opendesign_bundle.json")
    binding = resolve_runtime_binding(
        registry_root=registry_root,
        generation_root=generation_root,
        manifest=manifest,
    )
    return _real_directory(binding.data_dir, label="active OpenDesign data generation")


def project_root_relative_to_app_data(payload: dict[str, Any], project_id: str) -> str:
    """Return a scalar app-data-relative project root for a core-minted capability."""
    project_id = validated_identifier(project_id, label="OpenDesign project id")
    app_data_root = _real_directory(Path(str(payload.get("data_root") or "")), label="Design Studio data root")
    active = active_data_directory(payload)
    projects_root = _real_directory(active / "projects", label="OpenDesign projects root")
    project_path = projects_root / project_id
    if not project_path.exists():
        project_path.mkdir(mode=0o770)
    project_root = _real_directory(project_path, label="OpenDesign project root")
    try:
        return project_root.relative_to(app_data_root).as_posix()
    except ValueError as exc:
        raise RuntimeBridgeError("Active OpenDesign project root escapes app data.") from exc


class RuntimeCorrelationStore:
    """Strict per-generation store for transport metadata, not project data."""

    def __init__(self, active_data_root: Path) -> None:
        self.active_data_root = _real_directory(active_data_root, label="active OpenDesign data generation")
        self.root = self.active_data_root / BRIDGE_DIRECTORY
        self._ensure_root()
        self.path = self.root / CORRELATIONS_FILE
        self.lock_path = self.root / f".{CORRELATIONS_FILE}.lock"

    def list(self) -> list[dict[str, Any]]:
        with self._locked():
            return self._read()

    def get(self, od_run_id: str) -> dict[str, Any]:
        od_run_id = validated_identifier(od_run_id, label="OpenDesign run id")
        for record in self.list():
            if record.get("od_run_id") == od_run_id:
                return record
        raise RuntimeBridgeError("OpenDesign run correlation was not found.")

    def find_by_client_digest(self, digest: str) -> dict[str, Any] | None:
        return next((record for record in self.list() if record.get("client_request_digest") == digest), None)

    def find_by_runtime(self, runtime_session_id: str, turn_id: str) -> dict[str, Any] | None:
        return next(
            (
                record
                for record in self.list()
                if record.get("runtime_session_id") == runtime_session_id and record.get("turn_id") == turn_id
            ),
            None,
        )

    def insert(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        validated = _validated_record(record)

        def mutate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], tuple[dict[str, Any], bool]]:
            for existing in records:
                if existing["workspace_id"] == validated["workspace_id"] and existing["od_run_id"] == validated["od_run_id"]:
                    return records, (existing, False)
                if existing.get("client_request_digest") == validated.get("client_request_digest"):
                    return records, (existing, False)
            records.append(validated)
            records.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("od_run_id") or "")))
            return records, (validated, True)

        return self._update(mutate)

    def update(self, od_run_id: str, updater: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        od_run_id = validated_identifier(od_run_id, label="OpenDesign run id")

        def mutate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            for index, existing in enumerate(records):
                if existing.get("od_run_id") != od_run_id:
                    continue
                updated = _validated_record(updater(dict(existing)))
                if updated["od_run_id"] != od_run_id or updated["workspace_id"] != existing["workspace_id"]:
                    raise RuntimeBridgeError("Runtime correlation identity cannot change.")
                records[index] = updated
                return records, updated
            raise RuntimeBridgeError("OpenDesign run correlation was not found.")

        return self._update(mutate)

    def _update(self, updater):
        with self._locked():
            records = self._read()
            updated, result = updater(records)
            self._write(updated)
            return result

    @contextmanager
    def _locked(self):
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | _no_follow_flag(), 0o600)
        with os.fdopen(descriptor, "a+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        descriptor = os.open(self.path, os.O_RDONLY | _no_follow_flag())
        try:
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_CORRELATIONS_BYTES:
                raise RuntimeBridgeError("Runtime correlation store is not a bounded regular file.")
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                descriptor = -1
                raw = handle.read(MAX_CORRELATIONS_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(raw) > MAX_CORRELATIONS_BYTES:
            raise RuntimeBridgeError("Runtime correlation store exceeds its size limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeBridgeError("Runtime correlation store is not valid UTF-8 JSON.") from exc
        if not isinstance(payload, list):
            raise RuntimeBridgeError("Runtime correlation store must contain a JSON array.")
        return [_validated_record(item) for item in payload]

    def _write(self, records: list[dict[str, Any]]) -> None:
        encoded = (json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
        if len(encoded) > MAX_CORRELATIONS_BYTES:
            raise RuntimeBridgeError("Runtime correlation store exceeds its size limit.")
        temp = self.root / f".{CORRELATIONS_FILE}.{secrets.token_hex(8)}.tmp"
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _no_follow_flag(), 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                descriptor = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temp.unlink(missing_ok=True)

    def _ensure_root(self) -> None:
        if self.root.exists():
            _real_directory(self.root, label="runtime correlation root")
            return
        self.root.mkdir(mode=0o700)
        _real_directory(self.root, label="runtime correlation root")


def store_for_payload(payload: dict[str, Any]) -> RuntimeCorrelationStore:
    return RuntimeCorrelationStore(active_data_directory(payload))


def reserve_run(
    payload: dict[str, Any],
    *,
    project_id: str,
    conversation_id: str,
    assistant_message_id: str,
    client_request_id: str,
    agent_id: str,
) -> tuple[dict[str, Any], bool]:
    """Reserve one app-owned run id without retaining the browser request text."""
    project_id = validated_identifier(project_id, label="OpenDesign project id")
    conversation_id = validated_identifier(conversation_id, label="OpenDesign conversation id")
    assistant_message_id = validated_identifier(assistant_message_id, label="OpenDesign assistant message id")
    client_request_id = str(client_request_id or "").strip()
    if not client_request_id or len(client_request_id) > 512:
        raise RuntimeBridgeError("OpenDesign run requires a bounded clientRequestId.")
    digest = sha256(
        f"{payload.get('workspace_id')}\0{project_id}\0{conversation_id}\0{client_request_id}".encode("utf-8")
    ).hexdigest()
    store = store_for_payload(payload)
    existing = store.find_by_client_digest(digest)
    if existing is not None:
        return existing, False
    timestamp = utc_now()
    run_id = f"od_run_{uuid4().hex}"
    request_id = f"request_{digest[:24]}"
    record = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "workspace_id": str(payload.get("workspace_id") or ""),
        "local_app_id": str(payload.get("app_id") or ""),
        "sidecar_id": str(payload.get("sidecar_id") or "opendesign"),
        "od_project_id": project_id,
        "od_conversation_id": conversation_id,
        "od_run_id": run_id,
        "assistant_message_id": assistant_message_id,
        "agent_id": agent_id or "maverick",
        "runtime_session_id": "",
        "turn_id": "",
        "stream_id": "",
        "actor_id": str(payload.get("user_id") or "system"),
        "request_id": request_id,
        "correlation_id": request_id,
        "client_request_digest": digest,
        "attempt": 1,
        "idempotency_key": f"{run_id}:attempt-1",
        "last_sequence": 0,
        "status": "queued",
        "cancel_requested": False,
        "terminal_package_written": False,
        "result_package": None,
        "error": "",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return store.insert(record)


def record_submission(payload: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Persist core-stamped session/turn/stream identifiers from the callback."""
    run_id = validated_identifier(body.get("od_run_id"), label="OpenDesign run id")
    status = str(body.get("runtime_request_status") or "").strip()

    def update(record: dict[str, Any]) -> dict[str, Any]:
        if record["workspace_id"] != str(payload.get("workspace_id") or ""):
            raise RuntimeBridgeError("Runtime submission callback workspace mismatch.")
        record["runtime_session_id"] = str(body.get("runtime_session_id") or "")
        record["turn_id"] = str(body.get("turn_id") or "")
        record["stream_id"] = str(body.get("stream_id") or "")
        record["actor_id"] = str(body.get("actor_id") or record.get("actor_id") or "system")
        record["status"] = "queued" if status == "submitted" else "failed"
        record["error"] = "Runtime submission failed." if status != "submitted" else ""
        if status != "submitted":
            record["result_package"] = build_result_package(record, files=[])
            record["terminal_package_written"] = True
        record["updated_at"] = utc_now()
        return record

    return store_for_payload(payload).update(run_id, update)


def mark_cancel_requested(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    def update(record: dict[str, Any]) -> dict[str, Any]:
        record["cancel_requested"] = True
        record["updated_at"] = utc_now()
        return record

    return store_for_payload(payload).update(run_id, update)


def translate_stream_events(payload: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    run_id = validated_identifier(body.get("od_run_id"), label="OpenDesign run id")
    raw_events = body.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise RuntimeBridgeError("Runtime stream translation requires an ordered event batch.")
    events = [_validated_generic_event(item) for item in raw_events]
    expected = list(range(events[0]["sequence"], events[-1]["sequence"] + 1))
    if [event["sequence"] for event in events] != expected:
        raise RuntimeBridgeError("Runtime stream event sequence is not contiguous.")
    sse_events: list[dict[str, Any]] = []

    def update(record: dict[str, Any]) -> dict[str, Any]:
        if any(event["stream_id"] != record["stream_id"] for event in events):
            raise RuntimeBridgeError("Runtime stream event ownership mismatch.")
        acknowledged = int(record.get("last_sequence") or 0)
        if events[0]["sequence"] > acknowledged + 1:
            raise RuntimeBridgeError("Runtime stream event batch starts after an unacknowledged gap.")
        projection = dict(record)
        for event in events:
            translated = _translate_one_event(projection, event)
            if translated is not None:
                sse_events.append(translated)
            if event["sequence"] <= acknowledged:
                continue
            _translate_one_event(record, event)
            record["last_sequence"] = event["sequence"]
        if record["status"] in _TERMINAL_STATUS and not record.get("terminal_package_written"):
            record["result_package"] = build_result_package(record, files=[])
            record["terminal_package_written"] = True
        record["updated_at"] = utc_now()
        return record

    store_for_payload(payload).update(run_id, update)
    return {"ack_sequence": events[-1]["sequence"], "sse_events": sse_events}


def record_terminal(
    payload: dict[str, Any],
    *,
    runtime_session_id: str,
    turn_id: str,
    event_type: str,
    files: list[dict[str, Any]],
) -> dict[str, Any] | None:
    store = store_for_payload(payload)
    correlation = store.find_by_runtime(runtime_session_id, turn_id)
    if correlation is None:
        return None
    status = _terminal_status(event_type)

    def update(record: dict[str, Any]) -> dict[str, Any]:
        record["status"] = status
        record["error"] = "Runtime request failed." if status == "failed" else ""
        record["result_package"] = build_result_package(record, files=files)
        record["terminal_package_written"] = True
        record["updated_at"] = utc_now()
        return record

    return store.update(str(correlation["od_run_id"]), update)


def public_run(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["od_run_id"],
        "runId": record["od_run_id"],
        "status": record["status"],
        "projectId": record["od_project_id"],
        "conversationId": record["od_conversation_id"],
        "assistantMessageId": record["assistant_message_id"],
        "agentId": record["agent_id"],
        "createdAt": _epoch_ms(record["created_at"]),
        "updatedAt": _epoch_ms(record["updated_at"]),
        "cancelRequested": bool(record["cancel_requested"]),
        "exitCode": 0 if record["status"] == "succeeded" else 1 if record["status"] == "failed" else None,
        "signal": "SIGTERM" if record["status"] == "canceled" else None,
        **({"error": record["error"], "errorCode": "AGENT_EXECUTION_FAILED"} if record.get("error") else {}),
    }


def build_result_package(record: dict[str, Any], *, files: list[dict[str, Any]]) -> dict[str, Any]:
    safe_files = [item for item in files if isinstance(item, dict) and isinstance(item.get("name"), str)]
    artifacts = [artifact for item in safe_files if (artifact := _artifact_for_file(item)) is not None]
    return {
        "schema": "open-design.run-result-package.v1",
        "run": public_run(record),
        "workspace": {"storage": {"kind": "od-owned", "baseDir": None}, "provenance": None},
        "events": {"logPath": None},
        "project": {
            "id": record["od_project_id"],
            "name": record["od_project_id"],
            "fileCount": len(safe_files),
        },
        "artifacts": artifacts,
        "maverick": {
            "workspace_id": record["workspace_id"],
            "local_app_id": record["local_app_id"],
            "sidecar_id": record["sidecar_id"],
            "od_project_id": record["od_project_id"],
            "od_run_id": record["od_run_id"],
            "request_id": record["request_id"],
            "correlation_id": record["correlation_id"],
            "runtime_session_id": record["runtime_session_id"],
            "turn_id": record["turn_id"],
        },
    }


def validated_identifier(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise RuntimeBridgeError(f"{label} is invalid.")
    return text


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _translate_one_event(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event["event_type"]
    sequence = event["sequence"]
    data: dict[str, Any]
    name: str
    if event_type == "runtime.turn.queued":
        record["status"] = "queued"
        name, data = "start", {"runId": record["od_run_id"], "status": "queued"}
    elif event_type == "runtime.turn.started":
        record["status"] = "running"
        name, data = "start", {"runId": record["od_run_id"], "status": "running"}
    elif event_type in {"runtime.output.delta", "runtime.output.final"}:
        text = str(event["payload"].get("text") or "")
        if not text:
            return None
        name, data = "agent", {"type": "text_delta", "delta": text}
    elif event_type == "runtime.file.changed":
        name, data = "agent", {
            "type": "project_file_changed",
            "path": str(event["payload"].get("path") or ""),
            "change": str(event["payload"].get("change") or "modified"),
        }
    elif event_type in {
        "runtime.turn.completed",
        "runtime.turn.failed",
        "runtime.turn.cancelled",
        "runtime.turn.timed-out",
    }:
        record["status"] = _terminal_status(event_type)
        record["error"] = "Runtime request failed." if record["status"] == "failed" else ""
        name, data = "end", {
            "code": 0 if record["status"] == "succeeded" else 1 if record["status"] == "failed" else None,
            "signal": "SIGTERM" if record["status"] == "canceled" else None,
            "status": record["status"],
            "resumable": True,
            "endedWithUnfinishedWork": record["status"] != "succeeded",
            "artifactCount": 0,
            "failureCategory": "runtime" if record["status"] == "failed" else None,
            "failureDetail": record["error"] or None,
        }
    else:
        return None
    return {"id": str(sequence), "event": name, "data": data}


def _terminal_status(event_type: str) -> str:
    if event_type == "runtime.turn.completed":
        return "succeeded"
    if event_type == "runtime.turn.cancelled":
        return "canceled"
    return "failed"


def _validated_generic_event(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeBridgeError("Runtime stream event must be an object.")
    try:
        sequence = int(value.get("sequence"))
    except (TypeError, ValueError) as exc:
        raise RuntimeBridgeError("Runtime stream event sequence is invalid.") from exc
    event_type = str(value.get("event_type") or "")
    stream_id = str(value.get("stream_id") or "").strip()
    payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
    if sequence < 1 or event_type not in _GENERIC_EVENT_TYPES or not stream_id:
        raise RuntimeBridgeError("Runtime stream event identity is invalid.")
    return {
        "stream_id": stream_id,
        "sequence": sequence,
        "event_type": event_type,
        "payload": payload,
        "terminal": bool(value.get("terminal")),
    }


def _validated_record(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeBridgeError("Runtime correlation record must be an object.")
    record = dict(value)
    required = {
        "schema_version",
        "workspace_id",
        "local_app_id",
        "sidecar_id",
        "od_project_id",
        "od_conversation_id",
        "od_run_id",
        "assistant_message_id",
        "agent_id",
        "runtime_session_id",
        "turn_id",
        "stream_id",
        "actor_id",
        "request_id",
        "correlation_id",
        "client_request_digest",
        "attempt",
        "idempotency_key",
        "last_sequence",
        "status",
        "cancel_requested",
        "terminal_package_written",
        "result_package",
        "error",
        "created_at",
        "updated_at",
    }
    if set(record) != required:
        raise RuntimeBridgeError("Runtime correlation record schema changed.")
    if record["schema_version"] != BRIDGE_SCHEMA_VERSION:
        raise RuntimeBridgeError("Runtime correlation schema version is unsupported.")
    for key in ("workspace_id", "local_app_id", "sidecar_id", "od_project_id", "od_conversation_id", "od_run_id"):
        validated_identifier(record[key], label=key)
    if record["status"] not in {"queued", "running", "succeeded", "failed", "canceled"}:
        raise RuntimeBridgeError("Runtime correlation status is invalid.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record["client_request_digest"])):
        raise RuntimeBridgeError("Runtime correlation client digest is invalid.")
    if int(record["attempt"]) < 1 or int(record["last_sequence"]) < 0:
        raise RuntimeBridgeError("Runtime correlation sequence metadata is invalid.")
    for key in ("created_at", "updated_at"):
        try:
            timestamp = datetime.fromisoformat(str(record[key]))
        except ValueError as exc:
            raise RuntimeBridgeError("Runtime correlation timestamp is invalid.") from exc
        if timestamp.tzinfo is None:
            raise RuntimeBridgeError("Runtime correlation timestamp requires a timezone.")
    return record


def _artifact_for_file(item: dict[str, Any]) -> dict[str, Any] | None:
    name = str(item.get("name") or "").strip()
    if not name or name.startswith(".") or "/../" in f"/{name}/":
        return None
    suffix = Path(name).suffix.lower()
    renderer = "html" if suffix in {".html", ".htm"} else "image" if suffix in {".png", ".jpg", ".jpeg", ".svg", ".webp"} else "file"
    return {
        "file": name,
        "kind": renderer,
        "renderer": renderer,
        "title": Path(name).stem,
        "status": "complete",
        "manifest": {
            "version": 1,
            "kind": renderer,
            "title": Path(name).stem,
            "entry": name,
            "renderer": renderer,
            "status": "complete",
            "exports": [suffix.lstrip(".") or "file"],
        },
    }


def _epoch_ms(value: object) -> int:
    return int(datetime.fromisoformat(str(value)).timestamp() * 1000)


def _real_directory(path: Path, *, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise RuntimeBridgeError(f"{label} must be a real directory.")
        return path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RuntimeBridgeError(f"{label} is missing.") from exc


def _no_follow_flag() -> int:
    return getattr(os, "O_NOFOLLOW", 0)
