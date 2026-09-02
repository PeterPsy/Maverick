"""Certified public projections for variable hosted tool results."""

from __future__ import annotations

import hashlib
import re


INTER_AGENT_RESULT_PROJECTIONS = {
    "create": "inter-agent.run-create.v1",
    "spawn": "inter-agent.participant-spawn.v1",
    "send": "inter-agent.message-send.v1",
    "execute": "inter-agent.run-execute.v1",
    "wait": "inter-agent.run-wait.v1",
    "interrupt": "inter-agent.run-interrupt.v1",
    "resume": "inter-agent.run-resume.v1",
    "close": "inter-agent.run-close.v1",
}
INTER_AGENT_CLI_PROJECTIONS = {
    "inter-agent.runs.create": INTER_AGENT_RESULT_PROJECTIONS["create"],
    "inter-agent.participants.spawn": INTER_AGENT_RESULT_PROJECTIONS["spawn"],
    "inter-agent.messages.send": INTER_AGENT_RESULT_PROJECTIONS["send"],
    "inter-agent.runs.execute": INTER_AGENT_RESULT_PROJECTIONS["execute"],
    "inter-agent.runs.wait": INTER_AGENT_RESULT_PROJECTIONS["wait"],
    "inter-agent.runs.interrupt": INTER_AGENT_RESULT_PROJECTIONS["interrupt"],
    "inter-agent.runs.resume": INTER_AGENT_RESULT_PROJECTIONS["resume"],
    "inter-agent.runs.close": INTER_AGENT_RESULT_PROJECTIONS["close"],
}
INTER_AGENT_MCP_PROJECTIONS = {
    "inter_agent_run_create": INTER_AGENT_RESULT_PROJECTIONS["create"],
    "inter_agent_participant_spawn": INTER_AGENT_RESULT_PROJECTIONS["spawn"],
    "inter_agent_message_send": INTER_AGENT_RESULT_PROJECTIONS["send"],
    "inter_agent_execute": INTER_AGENT_RESULT_PROJECTIONS["execute"],
    "inter_agent_wait": INTER_AGENT_RESULT_PROJECTIONS["wait"],
    "inter_agent_interrupt": INTER_AGENT_RESULT_PROJECTIONS["interrupt"],
    "inter_agent_resume": INTER_AGENT_RESULT_PROJECTIONS["resume"],
    "inter_agent_close": INTER_AGENT_RESULT_PROJECTIONS["close"],
}
INTER_AGENT_EFFECTS = {
    "create": ("mutating", False),
    "spawn": ("mutating", False),
    "send": ("mutating", False),
    "execute": ("mutating", False),
    "wait": ("read", True),
    "interrupt": ("destructive", False),
    "resume": ("mutating", False),
    "close": ("destructive", False),
}

_RUN_STATUSES = {
    "created",
    "planning",
    "running",
    "paused",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
    "recovering",
}
_PARTICIPANT_STATUSES = {
    "idle",
    "planning",
    "running",
    "waiting",
    "blocked",
    "reviewing",
    "completed",
    "failed",
    "cancelled",
}
_TURN_STATUSES = {
    "queued",
    "active",
    "waiting_for_tool_confirmation",
    "completed",
    "failed",
    "cancelled",
    "timed-out",
}
_SESSION_STATUSES = {
    "created",
    "running",
    "stopping",
    "stopped",
    "failed",
    "recovery_required",
}
_PLATFORM_ID = {
    "run": re.compile(r"^iarun_[0-9a-f]{32}$"),
    "participant": re.compile(r"^iap_[0-9a-f]{32}$"),
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CERTIFIED_COMPONENT = "tool-schema-catalog"


def definition_has_certified_result_projection(definition) -> bool:
    """Return whether one exact Core definition owns a reviewed projector."""
    expected = _expected_projection(definition)
    return bool(
        expected
        and getattr(definition, "owner_kind", None) == "core"
        and getattr(definition, "schema_public", False) is True
        and getattr(definition, "certified_tcb_component", None)
        == _CERTIFIED_COMPONENT
        and getattr(definition, "agentic_result_projection", None) == expected
    )


def project_certified_tool_result(
    definition,
    result: dict[str, object],
) -> dict[str, object] | None:
    """Drop all content fields and emit only contract-bounded lifecycle metadata."""
    if not definition_has_certified_result_projection(definition):
        return None
    contract = str(definition.agentic_result_projection)
    operation = next(
        key for key, value in INTER_AGENT_RESULT_PROJECTIONS.items() if value == contract
    )
    if result.get("projection_contract") == contract:
        return _sanitize_existing_projection(contract, operation, result)
    projection: dict[str, object] = {
        "projection_contract": contract,
        "operation": operation,
        "outcome": "succeeded",
    }
    if operation in {"create", "execute", "wait", "resume"}:
        if not _project_run(result.get("run"), projection):
            return None
        participants = result.get("participants")
        if isinstance(participants, list):
            projection["participant_count"] = len(participants)
        if operation == "execute":
            participant_results = result.get("participant_results")
            if not isinstance(participant_results, list):
                return None
            projection["participant_result_count"] = len(participant_results)
            projection["final_answer_available"] = bool(result.get("final_answer"))
        return projection
    if operation == "spawn":
        participant = result.get("participant")
        session = result.get("runtime_session")
        if not isinstance(result.get("created"), bool):
            return None
        if not _project_participant(participant, projection):
            return None
        projection["created"] = result["created"]
        if isinstance(session, dict):
            _project_optional_id(session.get("session_id"), "runtime_session", projection)
            status = session.get("status")
            if status in _SESSION_STATUSES:
                projection["runtime_session_status"] = status
        return projection
    if operation == "send":
        if not _project_participant(result.get("participant"), projection):
            return None
        turn = result.get("turn")
        events = result.get("events")
        if not isinstance(turn, dict) or not isinstance(events, list):
            return None
        _project_optional_id(turn.get("turn_id"), "turn", projection)
        status = turn.get("status")
        if status not in _TURN_STATUSES:
            return None
        projection["turn_status"] = status
        projection["event_count"] = len(events)
        return projection
    if operation == "interrupt":
        if not _project_run(result.get("run"), projection):
            return None
        interrupted = result.get("interrupted_sessions")
        if not isinstance(interrupted, list):
            return None
        projection["interrupted_session_count"] = len(interrupted)
        return projection
    if operation == "close":
        if not _project_run(result.get("run"), projection):
            return None
        cleanups = result.get("participant_cleanups")
        deleted = result.get("deleted")
        if not isinstance(cleanups, list) or (
            deleted is not None and not isinstance(deleted, dict)
        ):
            return None
        projection["participant_cleanup_count"] = len(cleanups)
        projection["records_deleted"] = deleted is not None
        if isinstance(deleted, dict) and all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in deleted.values()
        ):
            projection["deleted_record_count"] = sum(deleted.values())
        return projection
    return None


def _expected_projection(definition) -> str | None:
    command_id = getattr(definition, "command_id", None)
    if isinstance(command_id, str):
        return INTER_AGENT_CLI_PROJECTIONS.get(command_id)
    tool_name = getattr(definition, "tool_name", None)
    if isinstance(tool_name, str):
        return INTER_AGENT_MCP_PROJECTIONS.get(tool_name)
    return None


def _sanitize_existing_projection(
    contract: str,
    operation: str,
    result: dict[str, object],
) -> dict[str, object] | None:
    """Make the projector idempotent without trusting already-shaped bytes."""
    if result.get("outcome") == "invalid_tool_result":
        return {
            "projection_contract": contract,
            "outcome": "invalid_tool_result",
        }
    if (
        result.get("operation") != operation
        or result.get("outcome") != "succeeded"
    ):
        return None
    projection: dict[str, object] = {
        "projection_contract": contract,
        "operation": operation,
        "outcome": "succeeded",
    }
    if operation in {"create", "execute", "wait", "interrupt", "resume", "close"}:
        if not _copy_reference(result, "run", projection, required=True):
            return None
        if not _copy_enum(result, "run_status", _RUN_STATUSES, projection):
            return None
    if operation in {"create", "execute", "wait", "resume"}:
        if not _copy_optional_count(result, "participant_count", projection):
            return None
    if operation == "execute":
        if not _copy_count(result, "participant_result_count", projection):
            return None
        if not _copy_bool(result, "final_answer_available", projection):
            return None
    if operation in {"spawn", "send"}:
        if not _copy_reference(result, "participant", projection, required=True):
            return None
        if not _copy_enum(
            result,
            "participant_status",
            _PARTICIPANT_STATUSES,
            projection,
        ):
            return None
    if operation == "spawn":
        if not _copy_bool(result, "created", projection):
            return None
        if not _copy_reference(
            result,
            "runtime_session",
            projection,
            required=False,
        ):
            return None
        if "runtime_session_status" in result and not _copy_enum(
            result,
            "runtime_session_status",
            _SESSION_STATUSES,
            projection,
        ):
            return None
    if operation == "send":
        if not _copy_reference(result, "turn", projection, required=False):
            return None
        if not _copy_enum(result, "turn_status", _TURN_STATUSES, projection):
            return None
        if not _copy_count(result, "event_count", projection):
            return None
    if operation == "interrupt" and not _copy_count(
        result,
        "interrupted_session_count",
        projection,
    ):
        return None
    if operation == "close":
        if not _copy_count(result, "participant_cleanup_count", projection):
            return None
        if not _copy_bool(result, "records_deleted", projection):
            return None
        if not _copy_optional_count(result, "deleted_record_count", projection):
            return None
    return projection


def _copy_reference(
    source: dict[str, object],
    label: str,
    destination: dict[str, object],
    *,
    required: bool,
) -> bool:
    identifier_field = f"{label}_id"
    digest_field = f"{label}_ref_sha256"
    identifier = source.get(identifier_field)
    digest = source.get(digest_field)
    present = int(identifier is not None) + int(digest is not None)
    if not present:
        return not required
    if present != 1:
        return False
    pattern = _PLATFORM_ID.get(label)
    if identifier is not None:
        if (
            pattern is None
            or not isinstance(identifier, str)
            or pattern.fullmatch(identifier) is None
        ):
            return False
        destination[identifier_field] = identifier
        return True
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        return False
    destination[digest_field] = digest
    return True


def _copy_enum(
    source: dict[str, object],
    field_name: str,
    allowed: set[str],
    destination: dict[str, object],
) -> bool:
    value = source.get(field_name)
    if value not in allowed:
        return False
    destination[field_name] = value
    return True


def _copy_count(
    source: dict[str, object],
    field_name: str,
    destination: dict[str, object],
) -> bool:
    value = source.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return False
    destination[field_name] = value
    return True


def _copy_optional_count(
    source: dict[str, object],
    field_name: str,
    destination: dict[str, object],
) -> bool:
    return field_name not in source or _copy_count(source, field_name, destination)


def _copy_bool(
    source: dict[str, object],
    field_name: str,
    destination: dict[str, object],
) -> bool:
    value = source.get(field_name)
    if not isinstance(value, bool):
        return False
    destination[field_name] = value
    return True


def _project_run(value: object, projection: dict[str, object]) -> bool:
    if not isinstance(value, dict) or value.get("status") not in _RUN_STATUSES:
        return False
    if not _project_required_id(value.get("run_id"), "run", projection):
        return False
    projection["run_status"] = value["status"]
    return True


def _project_participant(value: object, projection: dict[str, object]) -> bool:
    if not isinstance(value, dict) or value.get("status") not in _PARTICIPANT_STATUSES:
        return False
    if not _project_required_id(
        value.get("participant_id"),
        "participant",
        projection,
    ):
        return False
    projection["participant_status"] = value["status"]
    return True


def _project_required_id(
    value: object,
    label: str,
    projection: dict[str, object],
) -> bool:
    if not isinstance(value, str) or not value:
        return False
    _project_identifier(value, label, projection)
    return True


def _project_optional_id(
    value: object,
    label: str,
    projection: dict[str, object],
) -> None:
    if isinstance(value, str) and value:
        _project_identifier(value, label, projection)


def _project_identifier(
    value: str,
    label: str,
    projection: dict[str, object],
) -> None:
    platform_pattern = _PLATFORM_ID.get(label)
    if platform_pattern is not None and platform_pattern.fullmatch(value):
        projection[f"{label}_id"] = value
        return
    projection[f"{label}_ref_sha256"] = hashlib.sha256(
        value.encode("utf-8", errors="surrogatepass")
    ).hexdigest()


__all__ = [
    "INTER_AGENT_CLI_PROJECTIONS",
    "INTER_AGENT_EFFECTS",
    "INTER_AGENT_MCP_PROJECTIONS",
    "INTER_AGENT_RESULT_PROJECTIONS",
    "definition_has_certified_result_projection",
    "project_certified_tool_result",
]
