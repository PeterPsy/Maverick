---
name: maverick3-code-skill
description: "Use when working on the Maverick v3 codebase or when asked to implement, refactor, document, or review code in /home/ubuntu/maverick-v3. Enforces clean-slate v3 development: read AGENTS.md and docs/architecture first, avoid legacy/backward-compatibility shims, keep files small and maintainable, update architecture docs and IMPLEMENTATION_TASKLIST in the same change, and use frequent checkpoint commits/pushes during implementation."
---

# Maverick v3 Code Skill

Use this skill for code work in `/home/ubuntu/maverick-v3`.

## Required Read Order

Before changing code or structure, read:

1. `/home/ubuntu/maverick-v3/AGENTS.md`
2. `/home/ubuntu/maverick-v3/IMPLEMENTATION_TASKLIST.md`
3. the relevant architecture docs in `/home/ubuntu/maverick-v3/docs/architecture/`

Minimum architecture set:

- `core_architecture.md`
- `workspace_root_architecture.md`
- `app_contract_architecture.md`

## Non-Negotiable Rules

- treat `maverick-v3` as new software, not as a compatibility layer over `maverick-v2`
- do not preserve legacy names, folders, APIs, or behavior unless explicitly required
- do not add backward-compatibility shims by default
- keep `core/` as the direct package root of the platform core
- do not introduce wrapper folders like `backend/`, `runtime_backend/`, or `app/` inside `core/`
- do not leave stale references, dead code, commented-out code, or half-migrated structures behind

## Coding Workflow

1. Read the local repo guidance files first.
2. Check the existing tree before proposing structure changes.
3. Align the change with the relevant architecture docs.
4. Implement with small files and explicit names.
5. Update docs in the same change if architecture, layout, policy, or contracts moved.
6. Update `IMPLEMENTATION_TASKLIST.md` when a real implementation step is actually completed.
7. Run the smallest relevant validation.
8. Make frequent checkpoint commits and push meaningful progress regularly when working on the branch.

## File Design Heuristics

- prefer domain-oriented modules over generic helper buckets
- if a file is getting large, split it before it becomes hard to review
- prefer names like `service.py`, `models.py`, `store.py`, `routes.py`, `errors.py` when those responsibilities are real
- avoid speculative abstractions and premature extension points

## Documentation Discipline

When you change any of the following, update documentation in the same change:

- architecture
- filesystem layout
- package boundaries
- runtime behavior
- workspace behavior
- app contracts
- repository workflow expectations

Documentation ownership:

- `docs/architecture/` for architecture and contracts
- `AGENTS.md` for repository working rules
- `IMPLEMENTATION_TASKLIST.md` for implementation progress

## Preferred Next-Step Bias

When the codebase is still early-stage, prefer building foundations in this order:

1. repository conventions
2. filesystem and path contracts
3. workspace bootstrap and invariants
4. domain implementations on top of those contracts

Do not jump to higher-level features before the underlying filesystem and boundary rules are explicit.
