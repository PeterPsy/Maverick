---
name: maverick3-code-skill
description: "Use when working on Maverick v3 code, docs, tests, repository workflow, or pull requests. Guides agents to follow the repo's public development process, keep the v3 architecture clean, choose appropriate verification, update docs with behavior changes, and publish focused commits/PRs when asked."
---

# Maverick v3 Code Skill

Use this skill for Maverick v3 engineering work in the current repository or workspace.

This skill should orient the agent, not script every step. Read the local repository first, reason from the current code and docs, and choose the smallest reliable path to finish the user's goal.

## Source Of Truth

When present, read and follow:

- `AGENTS.md`
- `README.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `OPEN_SOURCE.md`
- `docs/architecture/core_architecture.md`
- `docs/architecture/workspace_root_architecture.md`
- `docs/architecture/app_contract_architecture.md`
- `IMPLEMENTATION_TASKLIST.md`

If code and docs disagree, fix the disagreement in the same change when it is in scope.

## Development Principles

- Treat Maverick v3 as clean-slate software.
- Do not add v2 compatibility shims, legacy names, or backward-compatibility layers unless a current written decision requires them.
- Keep `core/` as the direct platform package root.
- Keep platform concerns in core, app-owned behavior in apps, and workspace-owned data under `workspaces/<workspace_id>/`.
- Prefer simple domain-oriented modules over generic utility buckets.
- Delete obsolete structures when replacing them.
- Do not leave dead code, commented-out code, temporary debug code, generated junk, or stale references.
- Keep public-repository quality in mind: an external contributor should be able to understand, reproduce, test, and review the change.

## Working Process

For non-trivial work:

1. Inspect the relevant code, tests, docs, and current git state.
2. Identify the real boundary of the change before editing.
3. For bugs, reproduce or simulate the behavior before patching when practical.
4. Make the smallest maintainable change that solves the actual problem.
5. Update docs when architecture, workflow, setup, runtime behavior, workspace policy, app contracts, or security posture changes.
6. Run verification proportional to risk.
7. Review the diff before finishing.

Ask a clarifying question only when requirements are genuinely ambiguous or destructive. Otherwise, make reasonable assumptions and keep moving.

## Verification

Choose checks based on the change.

Baseline Python checks:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall core tests scripts
python3 scripts/check_unused_imports.py
```

For focused changes, run the smallest relevant subset first, then broaden if the risk or touched surface justifies it.

Frontend app checks:

```bash
cd apps/<app_id>
npm ci
npm run build
npm test --if-present
```

Repository hygiene checks:

```bash
git diff --check
rg -n "versy|maverick3\\.versy\\.ai|/home/ubuntu" -g '!node_modules/**'
```

Do not commit local state, `.env`, `.codex`, `.maverick/`, logs, `tmp/`, `output/`, Python caches, local databases, or runtime transcripts.

## Frontend And Generated Assets

Some built-in apps commit `frontend/dist/` so they mount from a fresh checkout.

When frontend source changes:

- rebuild the affected app
- commit source and committed dist together
- avoid unrelated generated churn
- follow `docs/development/generated_artifacts.md`

## Security Posture

Maverick is experimental and not production-ready.

When touching runtime, workspace isolation, auth, app hosting, app store, secrets, WebSockets, OAuth, deployment, or recovery:

- read `SECURITY.md` and the relevant part of `SECURITY_AUDIT.md`
- avoid weakening sandbox-first non-default workspace behavior
- avoid new default secrets, private hostnames, or local machine paths
- prefer fail-closed behavior for security boundaries
- document known limitations honestly

## Commits, Pushes, And PRs

Use focused commits as checkpoints when work is meaningful.

Before committing:

- inspect `git status -sb`
- review the diff
- stage only intended files unless the user explicitly asked to checkpoint the whole tree
- make sure relevant verification has passed or record why it could not run

When asked to publish work:

- commit with a clear message
- push the active branch
- open or update a PR when the GitHub tooling is available
- include what changed, why, tests run, docs changed, and security impact

PRs should stay focused. Do not bundle unrelated refactors, cleanup, feature work, and generated churn unless they are part of the same reviewable change.

## Maverick CLI And MCP Discovery

Do not guess app-owned CLI or MCP commands.

Use scoped machine-readable discovery:

```bash
maverick apps list --json
maverick core cli list --json
maverick core mcp list --json
maverick app <app_id> cli list --json
maverick app <app_id> mcp list --json
```

Treat `--help` as human syntax help, not as the primary agent discovery contract.

## Finishing Standard

A task is done when:

- the implementation and docs agree
- relevant tests or checks pass
- temporary files and caches are gone
- public-facing references are not private or machine-specific
- the diff is readable and scoped
- any commit, push, or PR requested by the user has been completed
