# Threat Model

Date: 2026-04-23

## Purpose

This document gives a compact threat model for Maverick as an experimental, self-hostable, workspace-isolated AI operating environment.

It is not a substitute for deeper internal security review notes.

Use this document to understand:

- what Maverick is trying to protect
- where the trust boundaries are
- which attackers are relevant
- what is intentionally not promised yet

## Security Position

Maverick is not production-ready.

The system is designed around stronger boundaries than a single-user personal assistant, especially for non-default workspaces, but the implementation still has open security hardening work.

Current intended position:

- `default` workspace may remain an explicitly unsafe full-access development workspace
- non-default workspaces are supposed to be sandbox-first and approval-gated
- app-owned data is not platform control-plane data
- runtime agents, app code, and generated content should be treated as untrusted by default

## Assets To Protect

Primary assets:

- user identities and authenticated sessions
- workspace membership and governance state
- app installation state and app enablement state
- workspace-owned app data under `workspaces/<workspace_id>/data/<app_id>/`
- runtime session state and turn history
- provider credentials and platform secrets
- local files outside the active workspace boundary
- app store trust and installed app artifacts

Secondary assets:

- logs and audit records
- generated files
- deployment configuration
- contributor trust in release artifacts and dependency metadata

## Trust Boundaries

### Browser user

The browser user is authenticated through the platform, but browser-origin trust is not enough authority for unsafe operations.

Unsafe requests, websocket channels, and mounted app surfaces must still be validated by core policy.

### Workspace user

A workspace user is trusted only for the workspace permissions granted by the control plane.

Workspace membership does not imply full host authority.

### App frontend

An app frontend is a mounted product surface, not a trusted control-plane authority.

App frontends may be buggy or malicious and should not be able to escalate through same-origin assumptions alone.

### App backend

An app backend is app-owned code executed under a platform contract.

It should not be treated as inherently trusted simply because the platform launches it.

### Runtime agent

A runtime agent is a powerful untrusted principal that can read context, call tools, and make planning decisions.

Prompt discipline is not an adequate security boundary.

### Provider subprocess

Provider subprocesses such as Codex are trusted only within the authority explicitly delegated by the core runtime and execution policy.

They are not generic host-level authorities.

### Platform core

The platform core is the policy and orchestration authority.

Compromise of the core is catastrophic, so the architecture should minimize paths to core compromise.

### Local host

The local host, filesystem, service manager, and operator account remain outside Maverick's internal policy model.

Local administrator compromise is considered out of scope for product-level isolation promises.

### External providers and remote services

OAuth providers, remote model providers, remote app catalogs, and external APIs are separate trust domains.

Data sent to them leaves the local trust boundary.

## Main Attacker Types

Relevant attackers:

- malicious workspace content author
- prompt-injection attacker through web pages, files, emails, tickets, or tool outputs
- compromised or malicious app author
- compromised or malicious app store artifact source
- low-privilege user attempting escalation
- browser-origin attacker exploiting weak session or websocket controls
- compromised provider or remote service
- operator mistake that exposes unsafe defaults to a public network

## Main Attack Paths

### Prompt injection leading to tool misuse

An agent reads hostile instructions and uses legitimate tools for unintended actions.

### Orchestrator-authored authority escalation

An untrusted orchestrator may attempt to create a worker with invented system
prompt, skills, provider, grants, or a disabled agent type. Dynamic
orchestration therefore accepts only task objective, dependency, role, review
target, and an optional id from the compact server-authorized agent catalog.
The core resolves the selected definition and prompt through Chat's configured
dependency provider, validates the runtime skill catalog, and materializes an
immutable participant snapshot. Invalid selections fail closed; they never
fall back to model-supplied authority-bearing fields.

The same output also cannot claim reserved topology identities such as the
run's orchestrator participant id. Dynamic task materialization rejects those
ids before mutation and reuses a persisted participant only when its hidden
agent kind, child-runtime execution mode, task label, agent type, task-bound
snapshot digest, skill ids, and provider material all match. This keeps a model
output from turning the root orchestrator into its own delegated worker.

### Participant output influencing the root generalist

The root generalist may receive a session-linked orchestration status read so
it can explain Agent nodes progress. That projection is read-only, bounded,
redacts common secret patterns, allowlists artifact reference fields, excludes
hidden participant runtime identifiers and raw tool payloads, and labels task
and result text as untrusted data rather than instructions. The original root
turn input remains the only user message persisted in the Chat transcript. The
provider-only attachment is applied in both synchronous and asynchronous
plain-hosted and agentic dispatch paths.

### Stale quality approval

An orchestrator may try to complete using an earlier approval after a later
review reports a critical issue. A completed negative or malformed reviewer or
security-reviewer verdict therefore requires completed material revision work
in its causal future before a later approval can pass; simply approving the
same unchanged output does not clear the veto. A failed reviewer task is also
fail-closed and remains unresolved until an approved retry or replacement
review depends causally on that failure. Every passing approval must still
cover the current material frontier.

### Workspace escape

A non-default workspace runtime or app process reads or writes outside the workspace boundary.

### Secret exposure

Secrets leak through files, logs, runtime state, generated files, or outbound actions.

Current mitigations require apps to persist only references or grant ids, keep raw values in AES-GCM Core Secrets envelopes, use action-scoped grants for app use, reject mixed-action wildcard target grants, require explicit targets for non-internal actions, validate structured HTTP/HTTPS targets or the `maverick://app.backend/*` platform delivery target family, strip query strings from audit targets, allowlist and bound audit request context, redact HTTP responses and audit payloads, fail closed with audit/event records when declared app-entrypoint grants are denied or missing, limit CLI/MCP delivery to command/tool descriptor `required_secrets`, ignore expired and non-deliverable grants during delivery selection, audit app-owned secret write create/rotate/grant operations, require admin authority for secret-mutating runtime CLI calls, and treat resolved values as ephemeral runtime input. Residual risk remains until the production secret backend, external key management, CSRF hardening, and app/runtime sandboxing blockers are closed.

### App privilege escalation

App frontend or backend code gains more authority than the app contract and workspace policy should allow.

### Session and identity abuse

Cookies, bearer tokens, or websocket channels are reused to perform privileged operations.

### Supply-chain compromise

Dependencies, app artifacts, or release artifacts are replaced or tampered with.

## Security Goals

The near-term goals are:

- sandbox-first isolation for non-default workspaces
- explicit approval gates for destructive or externally visible actions
- no silent privilege expansion from app or agent code
- clear separation between control-plane state and app-owned data
- explicit disclosure that current local bootstrap and deployment are not production-safe

## Non-Goals For The First Public Release

The first public release does not promise:

- hardened production secret storage
- safe internet-exposed deployment
- robust same-origin frontend isolation
- zero-trust multi-tenant guarantees
- unattended full-access recovery automation on sensitive hosts
- production-grade app sandboxing for every backend and lifecycle hook path

## Reviewer Checklist

Before treating a change as security-relevant, ask:

- does it cross a trust boundary?
- does it increase app or agent authority?
- does it expose secrets or session state?
- does it broaden filesystem access beyond the workspace?
- does it introduce new network egress or write paths?
- does it weaken documented launch limitations?
