# ADR-0003: Runtime Provider Abstraction

## Status

Accepted

## Context

Maverick currently uses Codex-backed runtime sessions, but the platform cannot be architected as if Codex were the only possible backend forever.

## Decision

- the runtime talks to providers through a provider abstraction
- provider sessions are linked to Maverick runtime sessions but remain provider-specific state
- Codex app-server is the current concrete backend, not the architectural definition of the runtime layer

## Consequences

- provider-specific launch rules stay in provider adapters
- runtime docs must describe both the generic model and current Codex assumptions
- provider prerequisites must be documented for external users
