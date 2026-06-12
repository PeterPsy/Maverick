---
name: fitness-coach-ops
description: Use Fitness Coach to manage workspace workouts, exercise library records, validation, and run summaries through Maverick MCP/CLI surfaces.
---

# Fitness Coach Operations

Use this skill when a user asks to create, inspect, update, duplicate, validate, or delete Fitness Coach workouts or reusable exercises in the current Maverick workspace.

## Source Of Truth

- Use Fitness Coach MCP tools for workout and exercise records.
- Use Storage surfaces for files, Drive, uploads, previews, and media streaming.
- Do not read or edit `data/fitness-coach/state.json` directly.
- Do not read `data/storage` or Google Drive tokens directly.
- Do not persist `stream_url`, raw Google/Drive URLs, local filesystem paths, token values, or `_app_secret_request` inside Fitness Coach records.

## V1 MCP Tools

Use only the V1 tools that are discoverable for `fitness-coach`:

- `fitness_coach_list_workouts`
- `fitness_coach_get_workout`
- `fitness_coach_create_workout`
- `fitness_coach_update_workout`
- `fitness_coach_duplicate_workout`
- `fitness_coach_delete_workout`
- `fitness_coach_validate_workout`
- `fitness_coach_list_exercises`
- `fitness_coach_get_exercise`
- `fitness_coach_create_exercise`
- `fitness_coach_update_exercise`
- `fitness_coach_delete_exercise`
- `fitness_coach_list_runs`

CLI action names mirror MCP semantics under the `fitness-coach` command:

- `workouts.list`
- `workout.get`
- `workout.create`
- `workout.update`
- `workout.duplicate`
- `workout.delete`
- `workout.validate`
- `exercises.list`
- `exercise.get`
- `exercise.create`
- `exercise.update`
- `exercise.delete`
- `runs.list`

## Media Rules

When attaching media, first resolve or select a Storage file or Drive file through Storage. Save only stable Storage references:

- local files: `file_id`, `workspace_relative_path`, `display_path`, `content_type`, `preview_kind`, and optional hash/version metadata;
- Drive files: `stable_storage_file_id`, `connection_id`, `drive_file_id`, `display_path`, `content_type`, `preview_kind`, and `source_version` or `etag_or_version`.

Fitness Coach V1 does not call Google Drive directly. Playback happens through Storage media stream or Drive localization at runtime.

## Delete Policy

Ask for explicit confirmation when a delete target is ambiguous, user intent is unclear, or multiple records match a name. Prefer resolving the exact id with list/get before deleting.

## Fitness Safety

Fitness Coach is not medical software. Do not diagnose, prescribe therapy, or promise clinical outcomes. If the user mentions pain, injury, pregnancy, medical conditions, or physical limitations, ask clarifying constraints and suggest consulting a qualified professional.

## Phase 2.0 Boundaries

Do not promise automatic video analysis, workout generation from a Drive folder, web suggestions, persistent media annotations, or async agent jobs. Those are Phase 2.0 concepts and are not available unless future discovery shows implemented tools.

## After Writes

After creating or modifying a workout, validate it with `fitness_coach_validate_workout` when the user wants to start it. Then open the app or provide the workspace route `/app/fitness-coach/workouts/<workout_id>` when useful.
