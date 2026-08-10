# Maverick Working Agreement

This repository is a clean rebuild of Maverick.

It must be developed as new software.

## Source Of Truth

Before changing structure or implementation, align with these files:

- `docs/architecture/core_architecture.md`
- `docs/architecture/workspace_root_architecture.md`
- `docs/architecture/app_contract_architecture.md`

These paths are repository-root source paths, not guaranteed paths relative to a runtime
workspace cwd such as `workspaces/default`.

Workspace agents must resolve these canonical documents through the core developer-context
surface before falling back to direct filesystem reads:

- `maverick core cli run developer-context.list --json`
- `maverick core cli run developer-context.read --doc-id core_architecture --json`
- `maverick core cli run developer-context.read --doc-id workspace_root_architecture --json`
- `maverick core cli run developer-context.read --doc-id app_contract_architecture --json`

Do not assume `docs/architecture/...` exists under the current working directory inside a
workspace runtime session.

If code, structure, and documentation disagree, fix the disagreement immediately.

Do not leave the repository in a state where the implementation has moved but the documentation still describes an older model.

## App Source Priority

When a task mentions an app id, first resolve app source from the Maverick root
repository:

```text
/home/ubuntu/projects/maverick-v3/apps/<app_id>
```

Built-in and general apps under root `apps/` are the primary source of truth for
code work. This includes apps such as `base-shell`, `chat`, `storage`, `agents`,
`skills`, `app-store`, and other platform-installed apps.

Only fall back to workspace-local app source when the app does not exist under
root `apps/`, or when the user explicitly says the task is about a
workspace-local app/fork:

```text
/home/ubuntu/projects/maverick-v3/workspaces/<workspace_id>/apps/<app_id>
```

Do not start app code discovery inside `workspaces/default/apps` for built-in or
general app work. Workspace-local apps are secondary. Workspace `data/<app_id>/`
is runtime data, not source.

Use bounded checks instead of broad parent-directory searches:

```bash
test -d apps/<app_id> && printf '%s\n' "apps/<app_id>"
test -d workspaces/default/apps/<app_id> && printf '%s\n' "workspaces/default/apps/<app_id>"
```

At the start of app code work, prefer this bounded orientation sequence:

```bash
pwd
git status -sb
test -f AGENTS.md && sed -n '1,220p' AGENTS.md
test -d apps/<app_id> && find apps/<app_id> -maxdepth 2 -type f | sort | sed -n '1,120p'
```

Do not run broad discovery from the repository parent, such as `find .. -name
AGENTS.md`, because it scans unrelated projects and may fail on directories
outside Maverick.

## Core Development Principles

- treat `maverick` as a clean-slate codebase
- do not preserve legacy names, folders, APIs, or behaviors just because they existed before
- do not add backward-compatibility shims unless explicitly required by a written implementation decision
- prefer deletion over compatibility layering when removing a wrong direction taken during development
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
- keep persistence technology details confined to store adapters and bootstrap wiring
- do not leak Mongo-specific shapes, raw driver payloads, or database-only types into domain models or service interfaces

## Planning And Clarification

- before implementing a non-trivial change, propose a short step-by-step plan
- if the user's request is not clear enough to implement safely, ask clarifying questions before coding
- do not guess through ambiguous product behavior, data model expectations, or destructive changes
- when requirements are clear enough to proceed, keep momentum and execute the plan end-to-end

## Test-Driven Development Bias

- prefer a test-driven approach for stable logic and contract work
- when practical, write or update the test that captures the intended behavior before or together with the implementation
- path contracts, filesystem rules, policy checks, and serialization logic should default to test-first work
- if test-first is not practical for a specific change, explain the reason briefly and still add the smallest useful test coverage

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
- if a task changes the intended target architecture, update the relevant architecture doc before or together with the code
- do not leave TODO notes as a substitute for updating documentation

## Skills

- Maverick product skills are app-owned extension data, not core assets.
- bundled Maverick skill templates may live under app-owned source directories such as `apps/skills/skills/`, `apps/chat/skills/`, or `apps/<app_id>/skills/`
- the Skills app seeds bundled templates by scanning `apps/*/skills/` for direct child directories that contain `SKILL.md`
- the Skills app copies those bundled skill templates into each workspace under `workspaces/<workspace_id>/data/skills/skills/`
- base runtime sessions may use every enabled workspace-owned skill copy from the workspace Skills app
- agent-type runtime sessions may narrow that set with the agent type's selected workspace skill ids
- do not rely on `~/.codex/skills`, plugin skills, or repository `local-skills/` as Maverick runtime skill sources
- Codex provider-generated system skills under `CODEX_HOME/skills/.system` are not Maverick product skills and must be removed from Maverick-managed runtime homes

## Maverick CLI And MCP Discovery

- do not guess app CLI or MCP commands, and do not inspect installation-level app source just to discover how to call an installed app
- use `maverick apps list --json` for compact installed-app discovery
- use `maverick core cli run developer-context.list --json` to discover canonical developer documents exposed by the core
- use `maverick core cli run developer-context.read --doc-id <doc_id> --json` to read one canonical developer document through the core
- use `maverick core cli list --json`, `maverick core cli inspect <command_id> --json`, and `maverick core cli run <command_id> ...` for core CLI commands
- use `maverick app <app_id> cli list --json`, `maverick app <app_id> cli inspect <command_name> --json`, and `maverick app <app_id> cli run <command_name> ...` for app CLI commands
- use `maverick app <app_id> frontend build --json` for official app frontend rebuilds so mounted clients receive the core refresh event
- use `maverick core mcp call developer-context.list` and `maverick core mcp call developer-context.read --doc-id <doc_id>` when the caller needs the same developer context over MCP
- use `maverick core mcp list --json`, `maverick core mcp inspect <tool_name> --json`, and `maverick core mcp call <tool_name> ...` for core MCP tools
- use `maverick app <app_id> mcp list --json`, `maverick app <app_id> mcp inspect <tool_name> --json`, and `maverick app <app_id> mcp call <tool_name> ...` for app MCP tools
- keep discovery scoped; do not ask the core for a merged list of every command and tool across every app
- treat `--help` as human command-line syntax help; use `list` and `inspect` for machine-readable agent discovery

## Testing And Verification

- new core logic should ship with tests when the behavior is stable enough to assert
- filesystem, path, policy, and contract logic should be covered early with focused unit tests
- run the smallest relevant verification for every change
- use `python3 scripts/test_suite.py --level fast` for the default development loop; it runs the self-contained fast suite and skips known slow app/bootstrap integration suites
- use `python3 scripts/test_suite.py --area <area>` for focused app/runtime/shell/authorization checks, and `python3 scripts/test_suite.py --level slow` or `--level pre-merge` only when slow integration coverage is intentionally required
- after refactors or file splits, run `python3 scripts/check_unused_imports.py` to catch stale imports that `compileall` cannot detect
- if a check cannot be run, state that clearly in the work summary
- do not claim a feature is complete if only the scaffold exists
- do not stop with failing tests when the failure is within the current scope to fix
- aim to leave the branch with all relevant tests passing before closing the task

## Long-Running Work Safety

- never detach agent-owned builds or test suites with cron, `nohup`, `tmux`,
  `screen`, `systemd-run`, or an equivalent mechanism; cancelling the runtime
  turn must also stop its descendants
- an operator-managed detached job requires explicit user authorization and a
  documented stop/status path; it must not be introduced merely to survive a
  runtime or backend restart
- do not start memory-intensive verification while the host is already under
  memory pressure; use app-owned safety gates and bounded worker counts where
  available
- after a core change that affects persisted control-plane shapes, complete
  focused tests and restart the backend before invoking state-mutating CLI or
  integration flows against it; verify health after restart so a new writer
  cannot leave an older in-memory reader serving incompatible records

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
- remove temporary debug code, scratch files, and experimental leftovers before finishing

## Review Pass

- always perform a final review pass after writing code
- review the diff for readability, unnecessary complexity, dead code, and documentation drift
- verify naming, file boundaries, and ownership still make sense after the implementation settled
- make the cleanup edits in the same change instead of leaving follow-up debt by default

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

## Document Operations Use Document Generator First

When the user asks to create, modify, transform, read, extract, convert, or
verify a workspace document or spreadsheet, use the Document Generator app
(`app_id: document-generator`) official CLI/MCP surfaces before installing or
using ad hoc local tools such as `openpyxl`, `xlsxwriter`, `pandas`, `xlsx`,
`xlsx2csv`, LibreOffice, or `soffice`.

This includes DOCX, PPTX, PDF, XLSX, CSV, and TSV work under
`storage/uploaded/` or `storage/generated/`. For spreadsheets, prefer
`spreadsheet.transform` with `write_cells`, `lookup_and_copy`, or `find_values`.
Fallback to direct libraries only when the official Document Generator surface
cannot express the requested operation or returns a concrete unsupported/failing
result, and state that fallback reason.
