---
name: maverick-v3-app-porting
description: "Use when planning or executing the porting or adaptation of an existing Maverick app into /home/ubuntu/maverick-v3, especially when studying an app from /home/ubuntu/maverick-v2 and producing a rigorous v3 app porting plan. Enforces v3 core/app architecture first, app-agnostic core boundaries, file-by-file legacy inventory, tasklist updates for missing generic core surfaces, and end-to-end ownership of the approved plan."
---

# Maverick v3 App Porting

Use this skill when porting or adapting an existing app into Maverick v3.

This skill is planning-first. Produce a rigorous plan before implementation unless the user explicitly asks to execute an already approved plan.

## Mandatory Pairing

Also use `maverick3-code-skill` for any task that touches `/home/ubuntu/maverick-v3`.

## Required Read Order

Before proposing an app plan or changing files, read:

1. `/home/ubuntu/maverick-v3/AGENTS.md`
2. `/home/ubuntu/maverick-v3/apps/skills/skills/maverick3-code-skill/SKILL.md`
3. `/home/ubuntu/maverick-v3/IMPLEMENTATION_TASKLIST.md`
4. `/home/ubuntu/maverick-v3/docs/architecture/core_architecture.md`
5. `/home/ubuntu/maverick-v3/docs/architecture/app_contract_architecture.md`
6. `/home/ubuntu/maverick-v3/docs/architecture/workspace_root_architecture.md`
7. relevant v3 core mounting code, usually `core/apps`, `core/api/platform_host.py`, `core/cli`, `core/mcp`, `core/skills`, `core/runtime`, `core/secrets`, and `core/observability`

Only inspect the legacy source app after the v3 architecture and core boundaries are clear.

## Required Inputs

Clarify these before implementation. If any are unknown, include the gap in the plan instead of guessing:

- source app path, for example `/home/ubuntu/maverick-v2/apps/<app_name>`
- target v3 app id, using canonical hyphenated form
- app kind: `frontend-only`, `backend-only`, `frontend+backend`, `mcp/cli-only`, `shell/host app`, or mixed
- distribution mode: sealed app-store artifact, source-available forkable app, or workspace-local app
- declared surfaces: frontend, backend, MCP, CLI, skills, lifecycle hooks, secrets, storage, export/import
- expected deploy target, if any

## Core Boundary Rules

- The v3 core may mount apps, route to app-owned surfaces, enforce policy, and expose generic platform capability.
- The v3 core must not know app business logic or contain app-specific conditionals.
- Do not add branches like `if app_id == "<specific-app>"` in core code.
- Do not preserve v2 API shapes in the core as compatibility shims.
- If an app needs a missing capability, add a generic core surface or document the gap in `IMPLEMENTATION_TASKLIST.md`.
- If a behavior is app-specific, implement it inside the app.

## Planning Workflow

1. Read the required v3 architecture and core files.
2. Inventory the source app in detail: manifests, frontend, backend, MCP, CLI, skills, hooks, assets, tests, storage, secrets, routes, environment assumptions, and external dependencies.
3. Classify every meaningful v2 file with the categories in `references/file-classification.md`.
4. Design the target v3 `app_contract.json` before coding.
5. Identify required generic core gaps separately from app implementation work.
6. Produce a file-by-file implementation plan using `references/port-plan-template.md`.
7. Include documentation, tasklist, tests, build, deployment, and smoke verification in the plan.
8. After approval or an explicit implementation request, execute the plan end-to-end and update docs/tasklist in the same change.

## Anti-Patterns

- copying legacy files blindly
- keeping legacy names or folders only for familiarity
- moving app logic into `core/`
- hardcoding optional app names in the shell or platform host
- committing `node_modules`, local env files, secrets, caches, or scratch artifacts
- treating `skills/` as an execution surface
- exposing app internals through core-specific shortcuts
- marking checklist items complete when only scaffold exists

## Definition Of Done

An app plan or port is not complete until it covers:

- valid v3 app identity and contract
- app-owned frontend/backend/MCP/CLI/skills surfaces, as applicable
- storage and data schema ownership
- lifecycle hooks, health, migration, export/import, and rollback expectations where relevant
- generic core gaps, documented without app-specific shortcuts
- docs and `IMPLEMENTATION_TASKLIST.md` updates
- tests and smoke checks
- final review for stale references, dead code, legacy paths, and core contamination
- checkpoint commit and push when implementation changes are made
