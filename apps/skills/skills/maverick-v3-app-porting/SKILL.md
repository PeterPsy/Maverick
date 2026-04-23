---
name: maverick-v3-app-porting
description: "Use when planning or executing the porting or adaptation of an existing Maverick app into the current workspace/repository. Enforces SDK-first v3 app creation, app-agnostic core boundaries, file-by-file source inventory, tasklist updates for missing generic core surfaces, and end-to-end ownership of the approved plan."
---

# Maverick v3 App Porting

Use this skill when porting or adapting an existing app into Maverick v3.

This skill is planning-first. Produce a rigorous plan before implementation unless the user explicitly asks to execute an already approved plan.

## Mandatory Pairing

Also use `maverick3-code-skill` for any task that touches Maverick v3 source or workspace app files.

## Immediate SDK Gate

When the port target is a workspace-local Maverick v3 app, check the official SDK before creating or editing the target app:

```bash
command -v maverick
maverick sdk templates
maverick sdk docs
```

If `maverick` is unavailable or `maverick sdk templates` fails, stop and report that the Maverick SDK runtime surface is unavailable. Use `maverick sdk docs` for SDK instructions instead of reading documentation files from disk. Do not create a manual v3 app fallback by copying existing app folders.

## Local Guidance

Before proposing an app plan or changing files, read `AGENTS.md` when it is present in the current workspace/repository.

Missing repository guidance in a workspace-only runtime is expected. Do not search outside the workspace and do not use missing docs as a reason to bypass SDK creation or lifecycle.

Core source inspection is only for platform-source work when those paths are present in the current repository checkout.

Only inspect the source app after the SDK target and workspace lifecycle are clear.

## Required Inputs

Clarify these before implementation. If any are unknown, include the gap in the plan instead of guessing:

- source app path, supplied by the user or present under the current workspace
- target v3 app id, using canonical hyphenated form
- app kind: `frontend-only`, `backend-only`, `frontend+backend`, `mcp/cli-only`, `shell/host app`, or mixed
- distribution mode: sealed app-store artifact, source-available forkable app, or workspace-local app
- declared surfaces: frontend, backend, MCP, CLI, skills, lifecycle hooks, secrets, storage, export/import
- expected deploy target, if any
- whether the official App SDK should create the initial v3 scaffold and validation/package flow

## Core Boundary Rules

- The v3 core may mount apps, route to app-owned surfaces, enforce policy, and expose generic platform capability.
- The v3 core must not know app business logic or contain app-specific conditionals.
- Do not add branches like `if app_id == "<specific-app>"` in core code.
- Do not preserve v2 API shapes in the core as compatibility shims.
- If an app needs a missing capability, add a generic core surface or document the gap in the relevant architecture or roadmap docs.
- If a behavior is app-specific, implement it inside the app.

## App SDK Use During Ports

The official Maverick App SDK is allowed and encouraged for v3 scaffold, validation, workspace-local registration, workspace-local installation, status inspection, and packaging.

Use the SDK for structure; do not use it as a compatibility layer.

Good SDK uses during porting:

- generate the initial v3 app root with the closest template: `minimal`, `frontend-backend`, `agent-tool`, `data-app`, or `widget`
- validate `app_contract.json` through `maverick app validate <app_id>`
- register/install workspace-local ports through `maverick app register-local <app_id>` and `maverick app install-local <app_id>`
- inspect source/registration/install state through `maverick app status <app_id>`
- package a valid app source through `maverick app package <app_id>`

Bad SDK uses during porting:

- preserving v2 APIs just because the scaffold makes it easy
- leaving generated placeholder behavior instead of ported product behavior
- copying v2 storage into the app without adapting it to `data/<app_id>`
- bypassing app-hosting with custom registration scripts

## Planning Workflow

1. Verify the SDK is available for the target workspace.
2. Inventory the source app in detail: manifests, frontend, backend, MCP, CLI, skills, hooks, assets, tests, storage, secrets, routes, environment assumptions, and external dependencies.
3. Classify every meaningful v2 file with the categories in `references/file-classification.md`.
4. Choose whether the SDK will generate the initial v3 source tree; if not, explain why.
5. Design the target v3 `app_contract.json` before coding.
6. Identify required generic core gaps separately from app implementation work.
7. Produce a file-by-file implementation plan using `references/port-plan-template.md`.
8. Include documentation, tests, build, deployment, SDK validation/status/package checks, and smoke verification in the plan.
9. After approval or an explicit implementation request, execute the plan end-to-end and update docs in the same change.

## Installation And Verification

Ported apps are not complete when files exist.

Every implemented port must finish with the correct generic app-hosting flow:

- installation-level apps under `apps/<app_id>` must register from `app_contract.json`, install/enable into the intended workspace when usable, and verify through generic app-hosting state
- workspace-local ports under `workspaces/<workspace_id>/apps/<app_id>` must validate, register, install, and verify with App Store/API/CLI/MCP/mount surfaces
- source-available forks must preserve provenance and install from the correct source or workspace-local fork record

Use SDK commands where appropriate:

```text
maverick app validate <app_id>
maverick app register-local <app_id>
maverick app install-local <app_id>
maverick app status <app_id>
maverick app package <app_id>
```

When verifying ported MCP or CLI surfaces, keep discovery scoped:

```text
maverick apps list --json
maverick app <app_id> cli list --json
maverick app <app_id> cli inspect <command_name> --json
maverick app <app_id> mcp list --json
maverick app <app_id> mcp inspect <tool_name> --json
```

Use `maverick core cli ...` and `maverick core mcp ...` only for core-owned commands and tools. Do not rely on a merged global list of all app and core commands.

## Anti-Patterns

- copying legacy files blindly
- keeping legacy names or folders only for familiarity
- moving app logic into `core/`
- hardcoding optional app names in the shell or platform host
- committing `node_modules`, local env files, secrets, caches, or scratch artifacts
- treating `skills/` as an execution surface
- exposing app internals through core-specific shortcuts
- using the SDK as a v2 compatibility wrapper
- leaving SDK scaffold behavior in place instead of ported behavior
- saying a port is complete before the app is registered, installed/enabled where intended, and smoke-tested through mounted surfaces
- marking checklist items complete when only scaffold exists

## Definition Of Done

An app plan or port is not complete until it covers:

- valid v3 app identity and contract
- SDK validation passes when the SDK is used
- app-owned frontend/backend/MCP/CLI/skills surfaces, as applicable
- storage and data schema ownership
- lifecycle hooks, health, migration, export/import, and rollback expectations where relevant
- generic core gaps, documented without app-specific shortcuts
- docs updates
- tests and smoke checks
- generic registration/install/enable status is verified for the target workspace when the app should be usable
- packaged artifact is produced when the port needs distribution
- final review for stale references, dead code, legacy paths, and core contamination
- checkpoint commit and push when implementation changes are made
