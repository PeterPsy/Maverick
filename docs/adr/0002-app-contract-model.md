# ADR-0002: App Contract Model

## Status

Accepted

## Context

Built-in apps and future external apps need a stable boundary for frontend, backend, MCP, CLI, skill, storage, and lifecycle integration.

## Decision

- every app integrates through an explicit app contract
- the core validates and mounts app surfaces but does not own app business logic
- app-owned data remains outside the core control plane
- app contracts are the authority for executable app surfaces and storage declarations

## Consequences

- apps can evolve without turning app internals into core APIs
- the core can remain headless and app-agnostic
- contributor docs must explain the contract model clearly
