# ADR-0005: Secret Storage Model

## Status

Accepted with launch limitation

## Context

Maverick needs local bootstrap secrets for development, but the current local JSON secret path is not sufficient for production.

## Decision

- local bootstrap may continue to use a development-oriented secret path for now
- production readiness is blocked on a stronger secret backend and tighter secret-delivery controls
- public docs must state that current secret handling is not production-safe

## Consequences

- launch messaging must stay conservative
- security docs must call out the current limitation directly
- future hardening work can replace the storage backend without changing the app/core ownership model
