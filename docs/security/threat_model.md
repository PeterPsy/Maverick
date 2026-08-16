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

### Explicit skill path injection

A client may attempt to invoke an unknown, disabled, or out-of-allowlist skill,
or to replace a stable skill id with a filesystem path or symlink escape. Turn
requests therefore accept only `invoked_skill_ids`. Core resolves those ids
from the runtime session's selected enabled catalog, enforces the session
allowlist, and the Codex adapter reconstructs `SKILL.md` only below the
session-local `codex-home/skills` copy. Missing files, symlinks, non-files, and
resolved paths outside that root fail closed before provider dispatch. Runtime
paths are not included in public API or transcript event payloads.

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
cover the current material frontier. An orchestrator cannot hide a negative or
failed verdict in an unbound reviewer task: reviewer and security-reviewer
tasks without a `review_of` target and direct target dependency are rejected in
both live decisions and persisted replay. Recovery also validates the complete
persisted initial DAG before adding any task to scheduler state, preventing
unknown review targets or dependency cycles from entering execution through a
sequence of individually valid task records. Operational event flooding also
cannot evict persisted plans, task results, control application markers,
handoffs, or directives: those allowlisted recovery records are protected from
visibility-history retention and internal replay reads every page in causal
order before scheduling resumes. If an older or corrupted run already lacks a
terminal task result, recovery fails closed rather than risking duplicate task
side effects. User interruption does not create that gap: an active task is
synchronously closed with a protected `cancelled` result even before its child
session exists. A paused-run fence before and after child creation removes late
session records and files before they can receive work. HTTP, CLI, and MCP
resume share a cross-process run-control handoff with interrupt cleanup, then
wait for the previous scheduler owner; sidecars without that owner reject the
mutation. Cleanup can cancel only the recovery generation, runtime session, and
task captured when the pause won. Runtime worker activation is independently
compare-and-set under a cross-process session lifecycle handoff and rereads the
persisted turn and session, so a cancelled turn or stopped session cannot be
resurrected by an older worker snapshot. Provider start has a second bounded
handoff from the final persisted `active`/executable check through provider
acceptance for both plain-hosted and agentic sync/async paths; prewarm uses the
session-only equivalent. Late provider and provider-thread metadata writes are
partial allowlisted mutations under the same handoff, so they cannot restore a
stopped session from an older full record. Interrupt also publishes a durable
first-writer cancellation intent before waiting for provider acceptance.
Activation, provider start, and terminal reconciliation treat it as
authoritative, ordinary lifecycle saves cannot erase it, and stale terminal
writes are corrected idempotently. Plain-hosted request owners watch that
intent and persist request-finished acknowledgement after aborting the HTTP
response, so an interrupt issued by CLI or MCP in another process does not
leave provider work alive. The acknowledgement is fenced by owner kind, host,
process id, process-start token, and request generation. Startup and interrupt
polling close only an exact same-host lease whose process incarnation is proven
dead; identity mismatch alone never declares a live sidecar dead, while
unverifiable or foreign-host owners fail closed. App, HTTP, and inter-agent
callers retry provider interruption after the lifecycle handoff, and publish
cancellation evidence only when the authoritative transition actually returns
`cancelled`. Concurrent HTTP or app interrupts atomically claim one durable
cancellation intent, and only that claimant reports successful interruption.
Terminal-outbox ownership is independent and technical: a worker or another
caller may drain the single event, thread-release, and source-app callback
phases without creating a second public success.
The same fence covers the complete scheduler mutation path. Each scheduler
captures one recovery generation, and every run transition, recovery-ledger
write, task claim/finalization, and completion commit validates that generation
and an active run status under the workspace transition lock. Queued futures
cannot start after pause, late results cannot overwrite persisted cancellation,
and a stale control decision cannot move a paused run to completed. Pause and
participant snapshot are committed under that lock, preventing a newly claimed
task from escaping cancellation. Runtime turn queueing is guarded by the same
status-and-generation transition: if pause wins, no turn is persisted or sent;
if queueing wins, interrupt observes and cancels that turn and its hidden session.
Same-turn message admission uses the same runtime-session `turn_submit` authorization as ordinary turn queueing. It requires a workspace-scoped client message id, a currently active Maverick turn, a persisted provider-acceptance correlation, and an adapter capability declaration before provider input is sent. The client never supplies a provider thread or turn id. Steer-or-queue decisions are serialized per session and refuse to overtake already queued turns. Admission state is persisted before crossing the provider boundary; explicit rejection releases it for safe next-turn queueing, while transport uncertainty remains terminal so browser retries cannot duplicate an input that may already have reached the provider.

### Workspace escape

A non-default workspace runtime or app process reads or writes outside the workspace boundary.

### Secret exposure

Secrets leak through files, logs, runtime state, generated files, or outbound actions.

Current mitigations require apps to persist only references or grant ids, keep raw values in AES-GCM Core Secrets envelopes, use action-scoped grants for app use, reject mixed-action wildcard target grants, require explicit targets for non-internal actions, validate structured HTTP/HTTPS targets or the `maverick://app.backend/*` platform delivery target family, strip query strings from audit targets, allowlist and bound audit request context, redact HTTP responses and audit payloads, fail closed with audit/event records when declared app-entrypoint grants are denied or missing, limit CLI/MCP delivery to command/tool descriptor `required_secrets`, ignore expired and non-deliverable grants during delivery selection, audit app-owned secret write create/rotate/grant operations, require admin authority for secret-mutating runtime CLI calls, and treat resolved values as ephemeral runtime input. Residual risk remains until the production secret backend, external key management, CSRF hardening, and app/runtime sandboxing blockers are closed.

### App privilege escalation

App frontend or backend code gains more authority than the app contract and workspace policy should allow.

For app-owned sidecars, browser and app-entrypoint authority are separate.
Entrypoints receive neither the sidecar port/technical token nor its private
persistence path. A core-owned Unix broker issues per-invocation capabilities
stored only by digest and bound to workspace, local app id, service, trusted
surface, actor, exact pass-through routes, TTL no greater than 30 seconds,
request budget, and body limits. Reference access is safe-read-only. Core strips
cookies and authorization, injects technical authentication only upstream,
audits issue/use/deny/revoke, and revokes at process completion. There is no
direct loopback or file fallback. Residual app-backend subprocess sandbox risk
remains a production blocker outside this transport boundary.

### Session and identity abuse

Cookies, bearer tokens, or websocket channels are reused to perform privileged operations.

Agent-facing historical transcript reads use the already lifecycle-validated
runtime bearer context but authorize the target separately. Same-workspace
membership and full-access execution are insufficient: only the target owner,
a workspace/platform admin, or a platform-minted `read_transcript` grant may
read it. Hidden inter-agent participant sessions and cross-workspace targets
fail closed as not found, and thread catalog filtering happens before search
and pagination so titles and counts do not leak. Transcript payloads are a
bounded allowlisted projection marked as untrusted conversation data. Opaque
snapshot cursors bind both event and turn eligibility to physical append
positions; timestamp ordering is applied only inside that immutable boundary.
Missing queued events may use pre-snapshot turn input only with an explicit
warning and incomplete projection, while mutable turn terminal state is ignored.
Structured keys are canonicalized across snake, kebab, and camel case before
sensitive-field filtering, and the projected structure has one global node and
serialized-byte budget with explicit truncation metadata. Read audits exclude
message content, prompts, tool output, paths, provider ids, and credentials.

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
