---
name: maverick3-code-skill
description: "Use when working on Maverick v3 code in the current workspace/repository or when asked to implement, refactor, document, or review code. Enforces clean-slate v3 development: read local working instructions when present, diagnose root causes with tests/simulations before patching, ask clarifying questions when requirements are not clear enough, propose a step plan before implementation, prefer test-driven work, keep files small and maintainable, update docs when behavior changes, perform a final review pass, and use frequent checkpoint commits and pushes during implementation."
---

# Maverick v3 Code Skill

Use this skill for Maverick v3 code work in the current workspace/repository root.

## Local Guidance

Before changing code or structure in a repository checkout, read `AGENTS.md` when it is present in the current workspace/repository.

If the current runtime is workspace-only and repository guidance is not present, do not search outside the workspace. Continue with workspace-local instructions and available Maverick commands.

## Non-Negotiable Rules

- treat `maverick-v3` as new software, not as a compatibility layer over `maverick-v2`
- do not preserve legacy names, folders, APIs, or behavior unless explicitly required
- do not add backward-compatibility shims by default
- keep `core/` as the direct package root of the platform core
- do not introduce wrapper folders like `backend/`, `runtime_backend/`, or `app/` inside `core/`
- do not leave stale references, dead code, commented-out code, or half-migrated structures behind
- do not patch symptoms before identifying the root cause with concrete evidence
- when discovering Maverick CLI or MCP capabilities, use scoped machine-readable discovery: `maverick core cli list --json`, `maverick core mcp list --json`, `maverick app <app_id> cli list --json`, and `maverick app <app_id> mcp list --json`
- treat `--help` as human syntax help, not as the agent discovery contract

## Diagnosis First

Before implementing a fix for a bug, regression, or unclear behavior:

1. Reproduce or simulate the issue with the smallest realistic input, event stream, API call, or unit test.
2. Inspect persisted state, runtime events, logs, or generated artifacts when they are part of the behavior.
3. Determine where the issue originates: producer, persistence, transport, projection, renderer, or UI state.
4. State the root cause and the intended fix boundary before editing production code.
5. Prefer fixing the producer or contract boundary over adding presentation-layer filters or special cases.

If the cause cannot be proven yet, continue diagnosis or ask the user for the missing information instead of applying a speculative patch.

## Coding Workflow

1. Read the local repo guidance files first.
2. If the request is not clear enough to implement safely, ask clarifying questions before coding.
3. Diagnose the root cause with tests, simulations, persisted state inspection, or runtime/event tracing before choosing an implementation.
4. Propose a short step-by-step plan before implementation for non-trivial work.
5. Check the existing tree before proposing structure changes.
6. Align the change with the current local contracts and documented behavior.
7. Prefer test-driven implementation for stable logic and contract work.
8. Implement with small files and explicit names.
9. Update docs in the same change if layout, policy, or contracts moved.
10. Run the smallest relevant validation and aim to leave all relevant tests passing.
11. Do a final review pass over the diff and remove temporary or dirty leftovers.
12. Make frequent checkpoint commits and push meaningful progress regularly when working on the branch.

## File Design Heuristics

- prefer domain-oriented modules over generic helper buckets
- if a file is getting large, split it before it becomes hard to review
- prefer names like `service.py`, `models.py`, `store.py`, `routes.py`, `errors.py` when those responsibilities are real
- avoid speculative abstractions and premature extension points
- remove temporary debugging code and experimental leftovers before finishing

## Documentation Discipline

When you change any of the following, update documentation in the same change:

- filesystem layout
- package boundaries
- runtime behavior
- workspace behavior
- app contracts
- repository workflow expectations

Documentation ownership:
- `AGENTS.md` for repository working rules

## Final Review Standard

Before closing the task:

- review the diff for readability and maintainability
- remove dead code, stale references, and unnecessary complexity
- make sure the tests relevant to the change pass
- do not leave the branch in a half-cleaned state

## Preferred Next-Step Bias

When the codebase is still early-stage, prefer building foundations in this order:

1. repository conventions
2. filesystem and path contracts
3. workspace bootstrap and invariants
4. domain implementations on top of those contracts

Do not jump to higher-level features before the underlying filesystem and boundary rules are explicit.
