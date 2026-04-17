# Maverick v3 Working Agreement

This repository is a clean rebuild of Maverick.

It must be developed as new software, not as an adaptation layer over `maverick-v2`.

## Source Of Truth

Before changing structure or implementation, align with these files:

- `docs/architecture/core_architecture.md`
- `docs/architecture/workspace_root_architecture.md`
- `docs/architecture/app_contract_architecture.md`
- `IMPLEMENTATION_TASKLIST.md`

If code, structure, and documentation disagree, fix the disagreement immediately.

Do not leave the repository in a state where the implementation has moved but the documentation still describes an older model.

## Core Development Principles

- treat `maverick-v3` as a clean-slate codebase
- do not preserve legacy names, folders, APIs, or behaviors just because they existed in `maverick-v2`
- do not add backward-compatibility shims unless explicitly required by a written implementation decision
- prefer deletion over compatibility layering when removing a wrong direction taken during v3 development
- keep the core headless, platform-oriented, and app-agnostic
- keep `core/` as the direct package root of the platform core
- do not introduce wrapper folders such as `backend/`, `runtime_backend/`, or `app/` inside `core/`
- do not introduce an ambiguous `core/core/`; use an explicit name such as `shared/` only when a shared package is truly necessary

## Code Quality Rules

- prefer small files with obvious ownership
- prefer domain-oriented modules over generic utility buckets
- avoid monolithic files; when a file is approaching roughly 250-300 lines, stop and evaluate whether it should be split
- keep each module focused on one responsibility
- prefer explicit names such as `workspace_registry.py` over vague names such as `helpers.py` or `misc.py`
- avoid speculative abstractions; create extension points only when there is a concrete second use case or a documented architectural need
- avoid copy-paste duplication; extract shared logic once the shared behavior is real
- do not leave commented-out code, dead code, placeholder compatibility branches, or unused scaffolding behind
- when replacing a structure or abstraction, remove the obsolete version in the same change unless there is a documented reason not to

## Preferred Core File Patterns

When a domain becomes real implementation code, prefer small explicit files such as:

- `routes.py`
- `service.py`
- `models.py`
- `store.py`
- `errors.py` when needed

This is a preference, not a reason to create empty ceremony. Start simple, then split once responsibilities become clear.

## Documentation Discipline

Documentation is mandatory engineering work in this repository.

Update documentation in the same change whenever you modify:

- architecture
- filesystem layout
- package boundaries
- runtime behavior
- app contracts
- workspace behavior
- implementation policy or workflow expectations

Rules:

- architecture decisions belong in `docs/architecture/`
- repository workflow and engineering discipline belong in `AGENTS.md`
- implementation progress belongs in `IMPLEMENTATION_TASKLIST.md`
- if a task changes the intended target architecture, update the relevant architecture doc before or together with the code
- if a task completes a real implementation step, mark the corresponding checklist items in `IMPLEMENTATION_TASKLIST.md`
- do not leave TODO notes as a substitute for updating documentation

## Local Skills

- repository-local Codex skills should live under `local-skills/`
- keep the versioned source of a Maverick v3 skill in this repository, not only in `~/.codex/skills`
- when a local skill should be available to Codex automatically, install it in `~/.codex/skills` with a symlink to the versioned repo path

## Testing And Verification

- new core logic should ship with tests when the behavior is stable enough to assert
- filesystem, path, policy, and contract logic should be covered early with focused unit tests
- run the smallest relevant verification for every change
- if a check cannot be run, state that clearly in the work summary
- do not claim a feature is complete if only the scaffold exists

## Filesystem And Workspace Discipline

- `workspaces/<workspace_id>/` is the tenant root for workspace-owned material
- app-owned workspace data must live under `workspaces/<workspace_id>/data/<app_id>/`
- platform infrastructure stays outside workspace roots
- non-default workspace assumptions must respect sandbox-first boundaries
- `default` may be special in execution policy, not in storage structure

## Clean Change Policy

Each change should leave the repository cleaner than it found it.

That means:

- fix stale references when you touch the surrounding area
- remove obsolete files when replacing them
- update paths after moving documents or modules
- keep the branch free of accidental generated artifacts

## Commit And Push Discipline

Frequent checkpoints are part of the development process in this repository.

Rules:

- make small, intentional commits during implementation instead of accumulating large unreviewable diffs
- push useful checkpoints regularly when working on a branch with meaningful progress
- use commits to preserve rollback points during active development, especially around structural refactors
- commit messages should describe the real architectural or implementation step taken
- do not bundle unrelated changes into the same commit
- do not use commit history as an excuse to leave the working tree messy or half-migrated

Recovery expectations:

- prefer moving forward with a corrective commit when a mistake is small and already understood
- use revert or branch-local rollback when a checkpoint clearly took the work in the wrong direction
- do not rewrite shared history casually
- if a rollback is needed, preserve repository clarity and documentation consistency as part of the recovery

## Decision Standard

When there are multiple valid implementations, prefer the one that is:

1. easier to read
2. easier to test
3. easier to delete or change later
4. more consistent with `docs/architecture/`

If a choice improves short-term speed but worsens the architecture, do not take it by default.
