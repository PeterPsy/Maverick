"""Domain service for the Fitness Coach app."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any, Callable
from uuid import uuid4

from core.app_sdk.storage import read_json_state, update_json_state, write_json_state

APP_ID = "fitness-coach"
STATE_FILE = "state.json"
SCHEMA_VERSION = 1
MAX_RUNS = 100
PREPARATION_BLOCK_SECONDS = 15

WORKOUT_WRITE_ACTIONS = {
    "workout.create",
    "workout.update",
    "workout.duplicate",
    "workout.delete",
    "workout.start",
}
EXERCISE_WRITE_ACTIONS = {"exercise.create", "exercise.update", "exercise.delete"}
RUN_WRITE_ACTIONS = {"workout.complete"}
VIEW_WRITE_ACTIONS = {"view_state.update", "set_view_filter", "set_custom_view", "clear_custom_view"}

ACTION_ALIASES = {
    "operations.manifest": "operations.manifest",
    "status": "status",
    "health.check": "status",
    "app.bootstrap": "app.bootstrap",
    "bootstrap": "app.bootstrap",
    "workouts.list": "workouts.list",
    "workout.list": "workouts.list",
    "workout.get": "workout.get",
    "workout.create": "workout.create",
    "workout.update": "workout.update",
    "workout.duplicate": "workout.duplicate",
    "workout.delete": "workout.delete",
    "workout.validate": "workout.validate",
    "workout.start": "workout.start",
    "workout.complete": "workout.complete",
    "exercises.list": "exercises.list",
    "exercise.list": "exercises.list",
    "exercise.get": "exercise.get",
    "exercise.create": "exercise.create",
    "exercise.update": "exercise.update",
    "exercise.delete": "exercise.delete",
    "runs.list": "runs.list",
    "view_state.get": "view_state.get",
    "view_state.update": "view_state.update",
    "reference_manifest": "reference_manifest",
    "references.manifest": "reference_manifest",
    "view_filter": "view_filter",
    "set_view_filter": "set_view_filter",
    "set_custom_view": "set_custom_view",
    "clear_custom_view": "clear_custom_view",
}

MCP_TOOL_ACTIONS = {
    "fitness_coach_list_workouts": "workouts.list",
    "fitness_coach_get_workout": "workout.get",
    "fitness_coach_create_workout": "workout.create",
    "fitness_coach_update_workout": "workout.update",
    "fitness_coach_duplicate_workout": "workout.duplicate",
    "fitness_coach_delete_workout": "workout.delete",
    "fitness_coach_validate_workout": "workout.validate",
    "fitness_coach_list_exercises": "exercises.list",
    "fitness_coach_get_exercise": "exercise.get",
    "fitness_coach_create_exercise": "exercise.create",
    "fitness_coach_update_exercise": "exercise.update",
    "fitness_coach_delete_exercise": "exercise.delete",
    "fitness_coach_list_runs": "runs.list",
    "fitness_coach_reference_manifest": "reference_manifest",
    "fitness_coach_view_filter": "view_filter",
    "fitness_coach_set_view_filter": "set_view_filter",
    "fitness_coach_set_custom_view": "set_custom_view",
    "fitness_coach_clear_custom_view": "clear_custom_view",
}


class FitnessCoachError(Exception):
    """Base app error with an HTTP-ish status code."""

    def __init__(self, message: str, *, status_code: int = 400, code: str = "validation_error") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class NotFoundError(FitnessCoachError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404, code="not_found")


class ConflictError(FitnessCoachError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=409, code="conflict")


def error_payload(error: FitnessCoachError) -> dict[str, object]:
    return {"ok": False, "error": error.code, "detail": error.message}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    canonical = canonical_action(action)
    resource = ""
    if canonical in WORKOUT_WRITE_ACTIONS:
        resource = "workouts"
    elif canonical in EXERCISE_WRITE_ACTIONS:
        resource = "exercises"
    elif canonical in RUN_WRITE_ACTIONS:
        resource = "runs"
    elif canonical in VIEW_WRITE_ACTIONS:
        resource = "view-state"
    if not resource:
        return []
    return [{"type": "maverick.app.data-changed", "owner_app_id": APP_ID, "resource": resource}]


def canonical_action(action: str) -> str:
    return ACTION_ALIASES.get(str(action or "").strip(), str(action or "").strip())


def default_state() -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "workouts": [],
        "exercises": [],
        "runs": [],
        "view_state": {
            "selected_workout_id": None,
            "setup_tab": "workout-settings",
            "sidebar_query": "",
            "custom_view": None,
        },
        "created_at": now,
        "updated_at": now,
    }


def ensure_state(data_root: str) -> dict[str, Any]:
    state = read_json_state(data_root, STATE_FILE, default_state())
    migrated = migrate_state(state)
    if migrated != state:
        write_json_state(data_root, STATE_FILE, migrated)
    return migrated


def handle_action(data_root: str, action: str, arguments: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    canonical = canonical_action(action)
    args = dict(arguments or {})

    if canonical == "operations.manifest":
        return 200, operations_manifest()
    if canonical == "reference_manifest":
        return 200, {"ok": True, "reference_manifest": {"entity_types": []}}
    if canonical == "status":
        state = ensure_state(data_root)
        return 200, {
            "ok": True,
            "status": "ready",
            "schema_version": state["schema_version"],
            "workout_count": len(state["workouts"]),
            "exercise_count": len(state["exercises"]),
            "run_count": len(state["runs"]),
        }
    if canonical == "app.bootstrap":
        return 200, {"ok": True, **bootstrap_app(data_root, args)}
    if canonical == "workouts.list":
        return 200, {"ok": True, "workouts": list_workouts(data_root, args)}
    if canonical == "workout.get":
        return 200, {"ok": True, "workout": get_workout(data_root, require_id(args, "workout_id", "id"))}
    if canonical == "workout.create":
        return 201, {"ok": True, "workout": create_workout(data_root, args)}
    if canonical == "workout.update":
        return 200, {"ok": True, "workout": update_workout(data_root, args)}
    if canonical == "workout.duplicate":
        return 201, {"ok": True, "workout": duplicate_workout(data_root, require_id(args, "workout_id", "id"), args)}
    if canonical == "workout.delete":
        return 200, {"ok": True, "deleted_id": delete_workout(data_root, require_id(args, "workout_id", "id"))}
    if canonical == "workout.validate":
        workout = get_workout(data_root, require_id(args, "workout_id", "id"))
        return 200, {"ok": True, "validation": validate_workout(workout)}
    if canonical == "workout.start":
        return 200, {"ok": True, **start_workout(data_root, require_workout_id(args), args)}
    if canonical == "workout.complete":
        return 201, {"ok": True, "run": complete_workout(data_root, args)}
    if canonical == "exercises.list":
        return 200, {"ok": True, "exercises": list_exercises(data_root, args)}
    if canonical == "exercise.get":
        return 200, {"ok": True, "exercise": get_exercise(data_root, require_id(args, "exercise_id", "id"))}
    if canonical == "exercise.create":
        return 201, {"ok": True, "exercise": create_exercise(data_root, args)}
    if canonical == "exercise.update":
        return 200, {"ok": True, "exercise": update_exercise(data_root, args)}
    if canonical == "exercise.delete":
        return 200, {"ok": True, "deleted_id": delete_exercise(data_root, require_id(args, "exercise_id", "id"))}
    if canonical == "runs.list":
        return 200, {"ok": True, "runs": list_runs(data_root, args)}
    if canonical == "view_state.get":
        return 200, {"ok": True, "view_state": ensure_state(data_root)["view_state"]}
    if canonical == "view_state.update":
        return 200, {"ok": True, "view_state": update_view_state(data_root, args)}
    if canonical == "view_filter":
        return 200, {"ok": True, "view_filter": view_filter(data_root)}
    if canonical == "set_view_filter":
        return 200, {"ok": True, "view_filter": set_view_filter(data_root, args)}
    if canonical == "set_custom_view":
        return 200, {"ok": True, "view_filter": set_custom_view(data_root, args)}
    if canonical == "clear_custom_view":
        return 200, {"ok": True, "view_filter": clear_custom_view(data_root)}
    raise FitnessCoachError(f"Unsupported action `{action}`.", status_code=400, code="unsupported_action")


def operations_manifest() -> dict[str, Any]:
    return {
        "ok": True,
        "app_id": APP_ID,
        "schema_version": str(SCHEMA_VERSION),
        "default_action": "operations.manifest",
        "commands": [{"surface": "cli", "name": "fitness-coach", "description": "Manage Fitness Coach workouts and exercise library records."}],
        "tools": [{"surface": "mcp", "name": tool, "operation": action} for tool, action in MCP_TOOL_ACTIONS.items()],
        "operations": [
            {"action": "app.bootstrap", "description": "Load initial app state in one backend action.", "optional": ["include_runs", "selected_workout_id", "runs_limit"]},
            {"action": "workouts.list", "description": "List workouts."},
            {"action": "workout.get", "required_any": ["workout_id", "id"]},
            {"action": "workout.create", "optional": ["name", "workout"]},
            {"action": "workout.update", "required_any": ["workout_id", "id", "workout.id"]},
            {"action": "workout.duplicate", "required_any": ["workout_id", "id"]},
            {"action": "workout.delete", "required_any": ["workout_id", "id"]},
            {"action": "workout.validate", "required_any": ["workout_id", "id"]},
            {"action": "exercises.list", "description": "List exercises."},
            {"action": "exercise.get", "required_any": ["exercise_id", "id"]},
            {"action": "exercise.create", "optional": ["title", "exercise"]},
            {"action": "exercise.update", "required_any": ["exercise_id", "id", "exercise.id"]},
            {"action": "exercise.delete", "required_any": ["exercise_id", "id"]},
            {"action": "runs.list", "description": "List bounded workout run summaries."},
        ],
        "safety": {
            "fitness_scope": "non_medical",
            "delete_policy": "Agents should ask confirmation for ambiguous deletions before invoking delete actions.",
        },
    }


def list_workouts(data_root: str, args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    state = ensure_state(data_root)
    query = normalized_text((args or {}).get("query")).lower()
    workouts = [deepcopy(item) for item in state["workouts"]]
    if query:
        workouts = [item for item in workouts if query in item.get("name", "").lower()]
    return sorted(workouts, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def bootstrap_app(data_root: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    state = ensure_state(data_root)
    args = args or {}
    summaries = [workout_summary(item) for item in sorted(state["workouts"], key=lambda item: str(item.get("updated_at") or ""), reverse=True)]
    selected_id = normalized_text(args.get("selected_workout_id")) or state["view_state"].get("selected_workout_id") or (summaries[0]["id"] if summaries else "")
    selected_workout = None
    if selected_id:
        try:
            selected_workout = deepcopy(find_by_id(state["workouts"], selected_id, "workout"))
        except NotFoundError:
            selected_workout = deepcopy(state["workouts"][0]) if state["workouts"] else None
            selected_id = selected_workout["id"] if selected_workout else ""
    view_state = deepcopy(state["view_state"])
    if selected_id:
        view_state["selected_workout_id"] = selected_id
    include_runs = bool(args.get("include_runs", False))
    return {
        "workspace_id": normalized_text(args.get("_workspace_id")),
        "app_id": normalized_text(args.get("_app_id")) or APP_ID,
        "state_version": state_version(state),
        "workouts": [deepcopy(item) for item in sorted(state["workouts"], key=lambda item: str(item.get("updated_at") or ""), reverse=True)],
        "workout_summaries": summaries,
        "selected_workout": selected_workout,
        "exercises": [deepcopy(item) for item in sorted(state["exercises"], key=lambda item: str(item.get("updated_at") or ""), reverse=True)],
        "tags": sorted({tag for exercise in state["exercises"] for tag in exercise.get("tags", []) if tag}),
        "runs": runs_from_state(state, {"workout_id": selected_id, "limit": args.get("runs_limit", 20)}) if include_runs else [],
        "view_state": view_state,
    }


def workout_summary(workout: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": workout.get("id"),
        "name": workout.get("name") or "Untitled workout",
        "work_block_count": count_work_blocks(workout),
        "estimated_seconds": estimate_seconds(workout),
        "updated_at": workout.get("updated_at"),
        "last_started_at": workout.get("last_started_at"),
        "last_completed_at": workout.get("last_completed_at"),
    }


def state_version(state: dict[str, Any]) -> str:
    return ":".join(
        [
            str(state.get("schema_version") or SCHEMA_VERSION),
            str(state.get("updated_at") or ""),
            str(len(state.get("workouts", []))),
            str(len(state.get("exercises", []))),
            str(len(state.get("runs", []))),
        ]
    )


def get_workout(data_root: str, workout_id: str) -> dict[str, Any]:
    state = ensure_state(data_root)
    return deepcopy(find_by_id(state["workouts"], workout_id, "workout"))


def create_workout(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    payload = object_arg(args, "workout")
    if not payload:
        payload = args
    created: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal created
        migrated = migrate_state(state)
        now = utc_now()
        workout = normalize_workout({**payload, "id": payload.get("id") or new_id("workout")}, now=now, existing=None)
        migrated["workouts"].append(workout)
        migrated["view_state"]["selected_workout_id"] = workout["id"]
        migrated["updated_at"] = now
        created = deepcopy(workout)
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return created


def update_workout(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    patch = object_arg(args, "workout") or dict(args)
    workout_id = str(patch.get("id") or args.get("workout_id") or args.get("id") or "").strip()
    if not workout_id:
        raise FitnessCoachError("workout_id or workout.id is required.")
    updated: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal updated
        migrated = migrate_state(state)
        index = find_index(migrated["workouts"], workout_id, "workout")
        now = utc_now()
        merged = {**migrated["workouts"][index], **patch, "id": workout_id}
        migrated["workouts"][index] = normalize_workout(merged, now=now, existing=migrated["workouts"][index])
        migrated["updated_at"] = now
        updated = deepcopy(migrated["workouts"][index])
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return updated


def duplicate_workout(data_root: str, workout_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    created: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal created
        migrated = migrate_state(state)
        source = deepcopy(find_by_id(migrated["workouts"], workout_id, "workout"))
        now = utc_now()
        source["id"] = new_id("workout")
        source["name"] = normalized_text((args or {}).get("name")) or f"{source['name']} Copy"
        source["created_at"] = now
        source["updated_at"] = now
        source["last_started_at"] = None
        source["last_completed_at"] = None
        for block in source.get("blocks", []):
            block["id"] = new_id("block")
        migrated["workouts"].append(source)
        migrated["view_state"]["selected_workout_id"] = source["id"]
        migrated["updated_at"] = now
        created = deepcopy(source)
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return created


def delete_workout(data_root: str, workout_id: str) -> str:
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        migrated = migrate_state(state)
        index = find_index(migrated["workouts"], workout_id, "workout")
        migrated["workouts"].pop(index)
        if migrated["view_state"].get("selected_workout_id") == workout_id:
            migrated["view_state"]["selected_workout_id"] = migrated["workouts"][0]["id"] if migrated["workouts"] else None
        migrated["updated_at"] = utc_now()
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return workout_id


def start_workout(data_root: str, workout_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    patch = object_arg(args or {}, "workout")

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal result
        migrated = migrate_state(state)
        index = find_index(migrated["workouts"], workout_id, "workout")
        existing = migrated["workouts"][index]
        workout = normalize_workout({**existing, **patch, "id": workout_id}, now=utc_now(), existing=existing) if patch else existing
        validation = validate_workout(workout)
        if not validation["valid"]:
            raise FitnessCoachError("Workout is not valid to start.", status_code=422, code="invalid_workout")
        now = utc_now()
        workout["last_started_at"] = now
        workout["updated_at"] = now
        migrated["workouts"][index] = workout
        migrated["view_state"]["selected_workout_id"] = workout_id
        migrated["updated_at"] = now
        result = {"workout": deepcopy(workout), "validation": validation, "started_at": now}
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return result


def complete_workout(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    workout_id = require_id(args, "workout_id", "id")
    saved: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal saved
        migrated = migrate_state(state)
        workout = find_by_id(migrated["workouts"], workout_id, "workout")
        now = utc_now()
        run = {
            "id": str(args.get("run_id") or new_id("run")),
            "workout_id": workout_id,
            "workout_name": workout["name"],
            "started_at": str(args.get("started_at") or workout.get("last_started_at") or now),
            "completed_at": str(args.get("completed_at") or now),
            "elapsed_seconds": positive_int(args.get("elapsed_seconds"), default=0, allow_zero=True),
            "completed_segments": positive_int(args.get("completed_segments"), default=0, allow_zero=True),
            "skipped_segments": positive_int(args.get("skipped_segments"), default=0, allow_zero=True),
            "exercise_count": positive_int(args.get("exercise_count"), default=count_work_blocks(workout), allow_zero=True),
        }
        migrated["runs"] = [run, *migrated["runs"]][:MAX_RUNS]
        workout["last_completed_at"] = run["completed_at"]
        workout["updated_at"] = now
        migrated["updated_at"] = now
        saved = deepcopy(run)
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return saved


def list_exercises(data_root: str, args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    state = ensure_state(data_root)
    args = args or {}
    query = normalized_text(args.get("query")).lower()
    tag = normalized_text(args.get("tag")).lower()
    exercises = [deepcopy(item) for item in state["exercises"]]
    if query:
        exercises = [
            item
            for item in exercises
            if query in item.get("title", "").lower()
            or query in item.get("short_description", "").lower()
            or query in item.get("long_description", "").lower()
        ]
    if tag:
        exercises = [item for item in exercises if tag in [str(value).lower() for value in item.get("tags", [])]]
    return sorted(exercises, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def get_exercise(data_root: str, exercise_id: str) -> dict[str, Any]:
    state = ensure_state(data_root)
    return deepcopy(find_by_id(state["exercises"], exercise_id, "exercise"))


def create_exercise(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    payload = object_arg(args, "exercise") or args
    created: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal created
        migrated = migrate_state(state)
        now = utc_now()
        exercise = normalize_exercise({**payload, "id": payload.get("id") or new_id("exercise")}, now=now, existing=None)
        migrated["exercises"].append(exercise)
        migrated["updated_at"] = now
        created = deepcopy(exercise)
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return created


def update_exercise(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    patch = object_arg(args, "exercise") or dict(args)
    exercise_id = str(patch.get("id") or args.get("exercise_id") or args.get("id") or "").strip()
    if not exercise_id:
        raise FitnessCoachError("exercise_id or exercise.id is required.")
    updated: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal updated
        migrated = migrate_state(state)
        index = find_index(migrated["exercises"], exercise_id, "exercise")
        now = utc_now()
        merged = {**migrated["exercises"][index], **patch, "id": exercise_id}
        migrated["exercises"][index] = normalize_exercise(merged, now=now, existing=migrated["exercises"][index])
        migrated["updated_at"] = now
        updated = deepcopy(migrated["exercises"][index])
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return updated


def delete_exercise(data_root: str, exercise_id: str) -> str:
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        migrated = migrate_state(state)
        index = find_index(migrated["exercises"], exercise_id, "exercise")
        used = [
            workout["name"]
            for workout in migrated["workouts"]
            for block in workout.get("blocks", [])
            if block.get("type") == "work" and block.get("exercise_id") == exercise_id
        ]
        if used:
            raise ConflictError(f"Exercise is used by workout snapshots: {', '.join(sorted(set(used)))}.")
        migrated["exercises"].pop(index)
        migrated["updated_at"] = utc_now()
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return exercise_id


def list_runs(data_root: str, args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    state = ensure_state(data_root)
    return runs_from_state(state, args)


def runs_from_state(state: dict[str, Any], args: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    args = args or {}
    workout_id = str(args.get("workout_id") or "").strip()
    limit = min(positive_int(args.get("limit"), default=MAX_RUNS), MAX_RUNS)
    runs = [deepcopy(item) for item in state["runs"]]
    if workout_id:
        runs = [item for item in runs if item.get("workout_id") == workout_id]
    return runs[:limit]


def update_view_state(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    saved: dict[str, Any] = {}

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal saved
        migrated = migrate_state(state)
        view = migrated["view_state"]
        if "selected_workout_id" in args:
            selected = args.get("selected_workout_id")
            view["selected_workout_id"] = str(selected) if selected else None
        if "setup_tab" in args:
            tab = str(args.get("setup_tab") or "")
            if tab not in {"workout-settings", "exercise-library"}:
                raise FitnessCoachError("setup_tab must be workout-settings or exercise-library.")
            view["setup_tab"] = tab
        if "sidebar_query" in args:
            view["sidebar_query"] = normalized_text(args.get("sidebar_query"))
        migrated["updated_at"] = utc_now()
        saved = deepcopy(view)
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return saved


def view_filter(data_root: str) -> dict[str, Any]:
    view = ensure_state(data_root)["view_state"]
    return {
        "mode": "custom" if view.get("custom_view") else "search",
        "query": view.get("sidebar_query") or "",
        "setup_tab": view.get("setup_tab") or "workout-settings",
        "selected_workout_id": view.get("selected_workout_id"),
        "custom_view": view.get("custom_view"),
    }


def set_view_filter(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    update_view_state(
        data_root,
        {
            "sidebar_query": args.get("query", args.get("sidebar_query", "")),
            "setup_tab": args.get("setup_tab", "workout-settings"),
            "selected_workout_id": args.get("selected_workout_id"),
        },
    )
    return view_filter(data_root)


def set_custom_view(data_root: str, args: dict[str, Any]) -> dict[str, Any]:
    custom_view = {
        "title": normalized_text(args.get("title")) or "Custom Fitness Coach view",
        "workout_ids": normalize_string_list(args.get("workout_ids")),
        "exercise_ids": normalize_string_list(args.get("exercise_ids")),
        "updated_at": utc_now(),
    }

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        migrated = migrate_state(state)
        migrated["view_state"]["custom_view"] = custom_view
        migrated["updated_at"] = custom_view["updated_at"]
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return view_filter(data_root)


def clear_custom_view(data_root: str) -> dict[str, Any]:
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        migrated = migrate_state(state)
        migrated["view_state"]["custom_view"] = None
        migrated["updated_at"] = utc_now()
        return migrated

    update_json_state(data_root, STATE_FILE, updater, default_state())
    return view_filter(data_root)


def validate_workout(workout: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    work_blocks = [block for block in workout.get("blocks", []) if block.get("type") == "work"]
    if not work_blocks:
        errors.append({"path": "blocks", "message": "Add at least one work block."})
    for index, block in enumerate(workout.get("blocks", [])):
        path = f"blocks[{index}]"
        if block.get("type") == "work":
            if not normalized_text(block.get("exercise_id")):
                errors.append({"path": f"{path}.exercise_id", "message": "Choose an exercise from the library."})
            if not normalized_text(block.get("title")):
                errors.append({"path": f"{path}.title", "message": "Title is required."})
            if not normalized_text(block.get("long_description") or block.get("short_description")):
                errors.append({"path": f"{path}.long_description", "message": "Description is required."})
            if block.get("mode") == "timer":
                if positive_int(block.get("seconds"), default=0, allow_zero=True) <= 0:
                    errors.append({"path": f"{path}.seconds", "message": "Timer work blocks need seconds > 0."})
            elif block.get("mode") == "reps":
                reps = positive_int(block.get("reps"), default=0, allow_zero=True)
                if reps <= 0 and not normalized_text(block.get("reps_label")):
                    errors.append({"path": f"{path}.reps", "message": "Reps work blocks need reps > 0 or a reps label."})
            else:
                errors.append({"path": f"{path}.mode", "message": "Work mode must be timer or reps."})
            media = block.get("media")
            if not isinstance(media, dict):
                errors.append({"path": f"{path}.media", "message": "Work blocks need image or video media."})
            else:
                media_error = media_playback_error(media)
                if media_error:
                    errors.append({"path": f"{path}.media", "message": media_error})
        elif block.get("type") == "rest":
            if positive_int(block.get("seconds"), default=0, allow_zero=True) <= 0:
                errors.append({"path": f"{path}.seconds", "message": "Rest blocks need seconds > 0."})
        else:
            errors.append({"path": path, "message": "Block type must be work or rest."})
    return {"valid": not errors, "errors": errors, "work_block_count": len(work_blocks), "estimated_seconds": estimate_seconds(workout)}


def media_playback_error(media: dict[str, Any]) -> str:
    if contains_forbidden_media_fields(media):
        return "Media refs cannot persist stream URLs, raw Drive URLs, tokens, local paths, or secret requests."
    kind = media.get("kind")
    preview_kind = media.get("preview_kind")
    if preview_kind not in {"video", "image"}:
        return "Only Storage image or video media are playable in V1."
    if kind == "local_file":
        if media.get("provider") != "local" or not str(media.get("file_id") or "").strip():
            return "Local media needs provider=local and file_id."
        if not str(media.get("workspace_relative_path") or "").startswith("storage/"):
            return "Local media needs a Storage workspace_relative_path."
        return ""
    if kind == "drive_file":
        if media.get("provider") != "google_drive":
            return "Drive media needs provider=google_drive."
        if not str(media.get("stable_storage_file_id") or "").strip():
            return "Drive media needs stable_storage_file_id."
        if not str(media.get("connection_id") or "").strip() or not str(media.get("drive_file_id") or "").strip():
            return "Drive media needs connection_id and drive_file_id."
        return ""
    return "Media kind must be local_file or drive_file."


def contains_forbidden_media_fields(value: Any) -> bool:
    forbidden = {"stream_url", "download_url", "local_path", "path", "_app_secret_request", "token", "access_token", "refresh_token"}
    if isinstance(value, dict):
        return any(key in forbidden or contains_forbidden_media_fields(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_forbidden_media_fields(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "drive.google.com" in lowered or "googleusercontent.com" in lowered
    return False


def normalize_workout(payload: dict[str, Any], *, now: str, existing: dict[str, Any] | None) -> dict[str, Any]:
    created_at = str((existing or {}).get("created_at") or payload.get("created_at") or now)
    default_work = positive_int(payload.get("default_work_seconds"), default=40)
    default_rest = positive_int(payload.get("default_rest_seconds"), default=20)
    default_reps = positive_int(payload.get("default_reps"), default=12)
    workout = {
        "id": str(payload.get("id") or (existing or {}).get("id") or new_id("workout")),
        "name": normalized_text(payload.get("name")) or "Untitled workout",
        "media_folder": normalize_folder_ref(payload.get("media_folder")),
        "default_work_seconds": default_work,
        "default_rest_seconds": default_rest,
        "default_reps": default_reps,
        "blocks": normalize_blocks(payload.get("blocks"), default_work=default_work, default_rest=default_rest, default_reps=default_reps),
        "created_at": created_at,
        "updated_at": now,
        "last_started_at": nullable_string(payload.get("last_started_at") if "last_started_at" in payload else (existing or {}).get("last_started_at")),
        "last_completed_at": nullable_string(payload.get("last_completed_at") if "last_completed_at" in payload else (existing or {}).get("last_completed_at")),
    }
    return workout


def normalize_exercise(payload: dict[str, Any], *, now: str, existing: dict[str, Any] | None) -> dict[str, Any]:
    media = normalize_media_list(payload.get("media"))
    primary = normalize_media_ref(payload.get("primary_media"))
    if primary is None and media:
        primary = deepcopy(media[0])
    if primary is not None and not any(same_media(primary, item) for item in media):
        media = [deepcopy(primary), *media]
    long_description = normalized_text(payload.get("long_description") or payload.get("description") or payload.get("short_description"))
    short_description = normalized_text(payload.get("short_description")) or summarize_description(long_description)
    return {
        "id": str(payload.get("id") or (existing or {}).get("id") or new_id("exercise")),
        "title": normalized_text(payload.get("title")) or "Untitled exercise",
        "short_description": short_description,
        "long_description": long_description,
        "tags": normalize_tags(payload.get("tags")),
        "primary_media": primary,
        "media": media,
        "source_folder": normalize_folder_ref(payload.get("source_folder")),
        "source_display_path": nullable_string(payload.get("source_display_path")),
        "created_at": str((existing or {}).get("created_at") or payload.get("created_at") or now),
        "updated_at": now,
    }


def normalize_blocks(raw_blocks: Any, *, default_work: int, default_rest: int, default_reps: int) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list):
        return []
    blocks: list[dict[str, Any]] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") == "rest":
            blocks.append({
                "id": str(raw.get("id") or new_id("block")),
                "type": "rest",
                "title": normalized_text(raw.get("title")) or "Rest",
                "short_description": normalized_text(raw.get("short_description")) or "Get ready for the next exercise.",
                "long_description": normalized_text(raw.get("long_description")) or "Breathe, reset, and preview the next movement.",
                "seconds": positive_int(raw.get("seconds"), default=default_rest),
                "show_next_exercise": bool(raw.get("show_next_exercise", True)),
                "skip_if_last": bool(raw.get("skip_if_last", True)),
            })
            continue
        mode = str(raw.get("mode") or "timer")
        if mode not in {"timer", "reps"}:
            mode = "timer"
        long_description = normalized_text(raw.get("long_description") or raw.get("description") or raw.get("short_description"))
        short_description = normalized_text(raw.get("short_description")) or summarize_description(long_description)
        blocks.append({
            "id": str(raw.get("id") or new_id("block")),
            "type": "work",
            "exercise_id": nullable_string(raw.get("exercise_id")),
            "exercise_snapshot_updated_at": nullable_string(raw.get("exercise_snapshot_updated_at")),
            "title": normalized_text(raw.get("title")),
            "short_description": short_description,
            "long_description": long_description,
            "tags": normalize_tags(raw.get("tags")),
            "mode": mode,
            "seconds": positive_int(raw.get("seconds"), default=default_work) if mode == "timer" else nullable_positive_int(raw.get("seconds")),
            "reps": positive_int(raw.get("reps"), default=default_reps) if mode == "reps" else nullable_positive_int(raw.get("reps")),
            "reps_label": nullable_string(raw.get("reps_label")),
            "media": normalize_media_ref(raw.get("media")),
            "notes": nullable_string(raw.get("notes")),
        })
    return blocks


def normalize_media_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    media: list[dict[str, Any]] = []
    for item in value:
        normalized = normalize_media_ref(item)
        if normalized is not None:
            media.append(normalized)
    return media


def normalize_media_ref(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if contains_forbidden_media_fields(value):
        raise FitnessCoachError("Media refs cannot contain stream_url, download_url, raw Drive URLs, tokens, local paths, or secret requests.")
    kind = str(value.get("kind") or "")
    preview_kind = str(value.get("preview_kind") or "")
    if preview_kind not in {"video", "image"}:
        preview_kind = "video" if str(value.get("content_type") or "").startswith("video/") else "image"
    base = {
        "display_path": normalized_text(value.get("display_path")),
        "name": normalized_text(value.get("name")),
        "content_type": normalized_text(value.get("content_type")),
        "preview_kind": preview_kind,
        "size_bytes": nullable_positive_int(value.get("size_bytes"), allow_zero=True),
        "etag_or_version": nullable_string(value.get("etag_or_version")),
        "capabilities": value.get("capabilities") if isinstance(value.get("capabilities"), dict) else {},
    }
    if kind == "drive_file" or value.get("provider") == "google_drive":
        return {
            "kind": "drive_file",
            "provider": "google_drive",
            "stable_storage_file_id": normalized_text(value.get("stable_storage_file_id") or value.get("file_id") or value.get("id")),
            "connection_id": normalized_text(value.get("connection_id")),
            "drive_file_id": normalized_text(value.get("drive_file_id")),
            "source_version": nullable_string(value.get("source_version")),
            **base,
        }
    return {
        "kind": "local_file",
        "provider": "local",
        "file_id": normalized_text(value.get("file_id") or value.get("id") or value.get("stable_storage_file_id")),
        "workspace_relative_path": normalized_text(value.get("workspace_relative_path")),
        "sha256": nullable_string(value.get("sha256")),
        **base,
    }


def normalize_folder_ref(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind") or "")
    if kind == "drive_folder" or value.get("provider") == "google_drive":
        return {
            "kind": "drive_folder",
            "provider": "google_drive",
            "connection_id": normalized_text(value.get("connection_id")),
            "drive_file_id": normalized_text(value.get("drive_file_id")),
            "display_path": normalized_text(value.get("display_path")),
        }
    if kind == "local_folder" or value.get("role") in {"uploaded", "generated"}:
        role = str(value.get("role") or "uploaded")
        if role not in {"uploaded", "generated"}:
            role = "uploaded"
        folder_relative_path = normalized_text(value.get("folder_relative_path") or value.get("relative_path"))
        return {
            "kind": "local_folder",
            "role": role,
            "folder_relative_path": folder_relative_path,
            "workspace_relative_path": normalized_text(value.get("workspace_relative_path")) or f"storage/{role}/{folder_relative_path}".rstrip("/"),
            "display_path": normalized_text(value.get("display_path")) or f"storage/{role}/{folder_relative_path}".rstrip("/"),
        }
    return None


def migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    base = default_state()
    migrated = {**base, **(state if isinstance(state, dict) else {})}
    migrated["schema_version"] = SCHEMA_VERSION
    migrated["workouts"] = [normalize_workout(item, now=str(item.get("updated_at") or migrated["updated_at"]), existing=item) for item in migrated.get("workouts", []) if isinstance(item, dict)]
    migrated["exercises"] = [normalize_exercise(item, now=str(item.get("updated_at") or migrated["updated_at"]), existing=item) for item in migrated.get("exercises", []) if isinstance(item, dict)]
    migrated["runs"] = [item for item in migrated.get("runs", []) if isinstance(item, dict)][:MAX_RUNS]
    view = migrated.get("view_state") if isinstance(migrated.get("view_state"), dict) else {}
    migrated["view_state"] = {
        "selected_workout_id": nullable_string(view.get("selected_workout_id")),
        "setup_tab": view.get("setup_tab") if view.get("setup_tab") in {"workout-settings", "exercise-library"} else "workout-settings",
        "sidebar_query": normalized_text(view.get("sidebar_query")),
        "custom_view": view.get("custom_view") if isinstance(view.get("custom_view"), dict) else None,
    }
    return migrated


def exercise_to_work_block(exercise: dict[str, Any], *, default_work_seconds: int = 40, default_reps: int = 12) -> dict[str, Any]:
    long_description = normalized_text(exercise.get("long_description") or exercise.get("description") or exercise.get("short_description"))
    short_description = normalized_text(exercise.get("short_description")) or summarize_description(long_description)
    return {
        "id": new_id("block"),
        "type": "work",
        "exercise_id": exercise["id"],
        "exercise_snapshot_updated_at": exercise.get("updated_at"),
        "title": exercise.get("title", ""),
        "short_description": short_description,
        "long_description": long_description,
        "tags": list(exercise.get("tags", [])),
        "mode": "timer",
        "seconds": default_work_seconds,
        "reps": default_reps,
        "reps_label": None,
        "media": deepcopy(exercise.get("primary_media")),
        "notes": None,
    }


def estimate_seconds(workout: dict[str, Any]) -> int:
    total = PREPARATION_BLOCK_SECONDS if count_work_blocks(workout) else 0
    blocks = workout.get("blocks", [])
    for index, block in enumerate(blocks):
        if block.get("type") == "work" and block.get("mode") == "timer":
            total += positive_int(block.get("seconds"), default=0, allow_zero=True)
        if block.get("type") == "rest":
            has_next_work = any(candidate.get("type") == "work" for candidate in blocks[index + 1 :])
            if block.get("skip_if_last") and not has_next_work:
                continue
            total += positive_int(block.get("seconds"), default=0, allow_zero=True)
    return total


def count_work_blocks(workout: dict[str, Any]) -> int:
    return len([block for block in workout.get("blocks", []) if block.get("type") == "work"])


def find_by_id(items: list[dict[str, Any]], item_id: str, label: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise NotFoundError(f"{label} `{item_id}` was not found.")


def find_index(items: list[dict[str, Any]], item_id: str, label: str) -> int:
    for index, item in enumerate(items):
        if item.get("id") == item_id:
            return index
    raise NotFoundError(f"{label} `{item_id}` was not found.")


def require_id(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(args.get(key) or "").strip()
        if value:
            return value
    raise FitnessCoachError(f"One of {', '.join(keys)} is required.")


def require_workout_id(args: dict[str, Any]) -> str:
    workout = object_arg(args, "workout")
    return require_id({**args, "workout.id": workout.get("id")}, "workout_id", "id", "workout.id")


def object_arg(args: dict[str, Any], key: str) -> dict[str, Any]:
    value = args.get(key)
    return dict(value) if isinstance(value, dict) else {}


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def summarize_description(value: Any, max_length: int = 140) -> str:
    text = normalized_text(value)
    if len(text) <= max_length:
        return text
    clipped = text[: max_length - 3].rstrip()
    last_space = clipped.rfind(" ")
    if last_space > 48:
        clipped = clipped[:last_space].rstrip()
    return f"{clipped}..."


def nullable_string(value: Any) -> str | None:
    text = normalized_text(value)
    return text or None


def normalize_tags(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else str(value or "").split(",")
    tags = []
    for item in raw:
        text = normalized_text(item).lower()
        if text and text not in tags:
            tags.append(text)
    return tags[:24]


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = normalized_text(item)
        if text and text not in items:
            items.append(text)
    return items[:200]


def positive_int(value: Any, *, default: int, allow_zero: bool = False) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    floor = 0 if allow_zero else 1
    return max(floor, number)


def nullable_positive_int(value: Any, *, allow_zero: bool = False) -> int | None:
    if value is None or value == "":
        return None
    return positive_int(value, default=0, allow_zero=allow_zero)


def same_media(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return str(left.get("file_id") or left.get("stable_storage_file_id")) == str(right.get("file_id") or right.get("stable_storage_file_id"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def write_default_state(data_root: str) -> None:
    write_json_state(data_root, STATE_FILE, default_state())
