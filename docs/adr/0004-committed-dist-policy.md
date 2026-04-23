# ADR-0004: Committed Dist Policy

## Status

Accepted

## Context

Some built-in apps must mount from a fresh checkout without requiring a frontend build as part of first-run evaluation.

## Decision

- selected built-in apps commit `frontend/dist/`
- committed dist remains policy until a stronger release-artifact pipeline replaces it
- source and committed build outputs must be updated together when frontend source changes

## Consequences

- contributors must understand when generated frontend assets are expected
- CI and docs must explain the reproducibility expectation
- reviews may include generated frontend churn for built-in apps
