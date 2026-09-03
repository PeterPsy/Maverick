# Core Architecture

Date: 2026-04-17

## Purpose

Define the target architecture of the Maverick core as a standalone, headless platform layer.

This document exists separately from the workspace architecture because the core must be redesigned with a clean and scalable boundary.

The goal is to describe:

- what the core is responsible for
- what the core is not responsible for
- how the core should be structured
- how the core should relate to workspaces, apps, and the runtime
- which official capability surfaces the core exposes

This document is intentionally platform-oriented.

It does not describe the internal business models of apps.

## Core Definition

The core is the platform runtime and control layer of Maverick.

It is not a business application.

It is not a content domain.

It is not the storage owner of app-owned workspace data.

The core should remain:

- headless
- standalone
- minimal
- stable
- app-agnostic

The repository layout for the core must reflect this directly:

- `core/` is the package root of the core
- the core code lives directly under `/maverick/core/`
- the core must not be nested under technical wrapper folders such as `backend/`, `runtime_backend/`, or `app/`
- the repository must not contain an ambiguous `core/core/` subtree

If internal shared utilities are needed, they should live under an explicit name such as `shared/` or `foundation/`, or be placed inside the owning domain when possible.

The core may expose more than one official executable capability surface while remaining headless:

- `mcp/`
- `cli/`

In addition, the core may ship instructional assets under:

- `skills/`

`skills/` is not an execution surface or enforcement boundary.

It is a procedural layer that explains how to use the core's executable surfaces.

## Initial Repository Conventions

The initial repository conventions should stay minimal and explicit:

- Python `3.12`
- the package root is the repository `core/` directory
- tests live under `/maverick/tests/`
- early verification should rely on standard-library-friendly commands first

At this stage the repository should prefer:

- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `python3 -m compileall core tests`

before introducing heavier toolchain assumptions.

The initial scaffold should also establish a small per-domain file pattern in the domains that become active first.

Preferred starter files, only when the domain has concrete implementation behind that boundary, are:

- `service.py`
- `models.py`
- `store.py`
- `errors.py` when a domain already owns explicit failure modes

Use `routes.py` only for real HTTP route wiring that is imported by the core host. Do not keep placeholder route modules that only describe future surfaces; domain intent belongs in architecture docs until executable wiring exists.

## Persistence Boundary

The Maverick domain model is storage-agnostic.

This applies in particular to:

- `models.py`
- `service.py`
- domain-level errors and contracts

`.maverick` is rebuildable installation-local operating material. Deleting `.maverick` must not delete the authoritative control-plane database, users, workspace links, OAuth/provider credential bindings, runtime token records, core usage samples and rollups, or secret values.

Hosted deployments use the configured durable control-plane store. The default adapter is JSON, selected with `MAVERICK_CONTROL_STORE=json` or by omitting `MAVERICK_CONTROL_STORE`. Its default root is `data/control-plane/json`, outside `.maverick`, so `.maverick` remains rebuildable installation-local operating material.

MongoDB is an optional adapter, selected with `MAVERICK_CONTROL_STORE=mongo` or by providing `MAVERICK_MONGODB_URI`. MongoDB is an implementation choice, not the architectural identity of the core.

Rules:

- domain records must not depend on Mongo driver types
- services should depend on store protocols or equivalent persistence contracts, not concrete Mongo adapters
- adapter-specific query shapes and update semantics must stay inside store adapters
- the JSON control-plane adapter must keep collection files and lock files writable by the shared operating group used by the service process and trusted local CLI operators, so one local sidecar command cannot rewrite a collection with permissions that make the hosted backend unable to read it
- bootstrap wiring may choose JSON, MongoDB, or another explicit adapter for platform-owned control-plane collections
- the selected control-plane adapter must not become the storage owner for app-owned workspace data
- migrating between control-plane adapters must be an explicit operator action with dry-run and validation; backend startup must not silently move or delete control-plane state
- adapter migration must preserve the source adapter data during target preparation so rollback remains an operator configuration decision until cutover has been verified
- adapter migration surfaces belong to the core HTTP, CLI, and MCP layers; admin apps may call them but must not own adapter semantics or persistence code
- a prepared adapter migration must not hot-swap stores inside a live process; cutover happens on backend restart so exactly one control-plane adapter is mounted at a time
- deletion of old adapter storage must be post-cutover cleanup, scheduled only after target write and configuration update, and executed only after the restarted backend is healthy
- generated service environment files contain durable secrets and must not be stored under `.maverick`
- the control-plane database is not encrypted as a whole; sensitive values must use the core secret domain instead of raw database or environment fields
- database passwords, runtime signing secrets, widget signing secrets, provider API keys, and OAuth client secrets must be stored as core secret values or bootstrap secret refs, not as raw `.env` values
- the secret-store encryption key should be loaded from a local key file such as `MAVERICK_SECRET_KEY_FILE`; `MAVERICK_SECRET_STORE_KEY` is a development/backward-compatibility fallback

This keeps the core open to future adapters such as PostgreSQL, SQLite, or another control-plane store without reshaping the domain model.

### Secret Handling

The `core.secrets` domain is the platform-wide secret system. It owns encrypted secret value envelopes and authorization rules for delivering scoped values to apps, providers, runtime sessions, and platform infrastructure code.

Apps and agents must persist only secret references, grant ids, logical names, and non-sensitive metadata. Raw secret values may be accepted only by platform-owned secret write or rotation surfaces, must be encrypted into the core secret store, and must never be returned to browser clients, ordinary CLI/MCP metadata calls, logs, workspace files, chat transcripts, or generated artifacts.

App use is grant-based. A `SecretGrantRecord` binds a `secret_ref` to a workspace, app, logical name, allowed actions, optional target patterns, optional resource identity, expiry, and audit metadata. Runtime resolution for app actions must validate the grant before decrypting the value, deliver the value only as ephemeral input to the controlled execution path, and record allow or deny audit events without including the raw value. Declared app-entrypoint delivery is fail-closed for every requested logical name: a missing current grant is a denial with audit/event records when the request marks the secret required, expired active grants are ignored for delivery and replacement selection, non-`app.backend` grants are ignored during entrypoint delivery candidate selection, and audit request context is allowlisted and bounded before persistence. Mounted app backends may request a declared subset of logical names and may include `resource_type` plus `resource_id` so per-resource secrets, such as one OAuth refresh token per account connection, are delivered only for the requested resource instead of all grants for the app logical name. Grant creation and app-owned secret writes must derive a logical name's workspace-scoped or resource-scoped mode from the same app consumer metadata used by grant-target inventory, and the core must reject grants whose resource scope does not match that mode.

Admin-only Core Secrets inventory may expose issue-oriented logical needs for Vault and agents. That surface must derive needs and recommended grants from app contracts plus CLI/MCP descriptor secret selectors, prefer the narrowest synthetic app-backend delivery targets that cover the declared consumers, include workspace or resource scope, report missing values and missing, expired, revoked, orphaned, or stale grants as redaction-safe state, and return confidence/ambiguity metadata for credential matches. It must never return raw secret values or let Vault reconstruct delivery policy in frontend code.

The core must not introduce a separate product secret system for infrastructure credentials. Pre-adapter infrastructure secrets, such as a MongoDB password needed before a Mongo connection can be opened, may live in a local bootstrap secret store backed by the same `SecretDocumentStore` envelope format and the same secret key loader.

Workspace agents must not receive filesystem access to `.env.maverick`, secret key files, bootstrap secret files, or raw control-plane secret value storage. Full-access sessions are operator break-glass sessions and should be treated as capable of reading host-level secrets.

## Core Responsibilities

The core is responsible for the following domains.

### 1. Identity and access

The core owns:

- users
- authentication
- sessions
- workspace membership
- workspace governance

This includes who can enter the system and which workspaces they can access.

The control-plane persistence for these records may target JSON, MongoDB, or a future adapter, while keeping the domain records and service layer independent from HTTP, framework-specific exceptions, and database-driver-specific types.

### 2. Workspace registry and governance

The core owns:

- workspace existence
- workspace metadata
- workspace governance state
- workspace quotas and limits
- workspace policy enforcement

The core does not own the internal business data of a workspace.

The initial model should keep these records distinct:

- workspace registry record
- workspace membership record
- workspace governance record
- workspace quota record

The execution-policy domain may read these records, but it should still compute the effective runtime policy separately.

Only platform admins may create new workspaces through the hosted platform API.

Platform members may list and enter workspaces where they have active membership, but they must not create workspace records. Workspace assignment for members is an admin control-plane action.

### 3. App installation and hosting

The core owns:

- local installation state of apps
- app enablement state per workspace
- app lifecycle orchestration
- app hosting contracts
- app runtime hooks such as install, upgrade, migrate, uninstall

The core does not own app business data.

App hosting also exposes one generic sidecar lifecycle capability named from
the local binding, `app.<id>.sidecars.restart`. It is valid only for an enabled
workspace binding whose contract declares at least one HTTP sidecar. The core
revokes browser tickets and sessions scoped to that workspace and app, stops
only that binding's declared sidecar processes, starts them again, waits for
their declared readiness, writes redaction-safe audit evidence, and publishes
a workspace/app-scoped `maverick.app.runtime-changed` event. The capability
does not know why a sidecar is restarting and must not contain app-specific
artifact, migration, or protocol logic.

Governed recovery also has a generic, owner-authenticated sidecar quarantine.
Core persists the workspace/app fence in its control plane before attempting
process cleanup. An active fence denies HTTP proxy and isolated-browser
resolution, declarative prewarm, restart, relay reuse, and new model-access
leases. Core revokes browser sessions and every matching model lease, including
cancellation of requests already open at the broker, before making a bounded
process-stop attempt. The fence survives Core restart and is removed only by an
explicit recovery release; releasing it never starts a process implicitly.
This quarantine contains no app-specific migration or data knowledge.

The app-hosting domain should keep at least these concepts distinct:

- app source or project material
- app distribution artifact
- app installation record
- workspace app enablement or binding state

These concepts are related, but they are not interchangeable.

Examples:

- a server app store artifact under `/apps` may be known to the installation without being enabled in every workspace
- a workspace-local app project may exist under `workspaces/<workspace_id>/apps/` without being installed yet
- an installed app may be disabled in one workspace while remaining enabled in another

This separation is required to keep lifecycle orchestration, compatibility checks, and uninstall or reinstall behavior deterministic.

The core also owns the generic resolver for app interface dependencies declared in app contracts.

This resolver is deliberately app-agnostic:

- provider apps advertise typed interfaces in `provides`
- consumer apps declare typed requirements in `requires`
- workspace users select concrete enabled provider apps per consumer alias
- the core validates interface id, version compatibility, provider visibility, and workspace enablement
- the core persists only workspace-scoped dependency selections, not app product data

The core must not special-case app ids such as `fleet`, `agents`, `storage`, or a file provider app. A cross-app consumer depends on interface types such as `agent.catalog` or `file.preview`; the shell and the consumer app receive resolved provider ids after the workspace selection is made. If a provider app is disabled or uninstalled, the selection becomes stale until setup is corrected.

The app-hosting domain must also separate public app identity from workspace-local binding identity.

- `public_app_id` identifies the distributed app artifact or catalog entry declared by the app contract.
- `local_app_id` identifies one workspace binding, app-owned data namespace, and user-facing app instance inside that workspace.
- `mount_app_id` identifies the concrete route namespace used by mounted HTTP, WebSocket, and widget surfaces, normally equal to `local_app_id`. CLI command ids and MCP tool ids use `local_app_id`; entrypoint payloads also receive `public_app_id` so app-owned code can distinguish the source artifact from the workspace-local binding.

Built-in apps may use the same value for all three, but the core must not require that equality. App Store install, fork, dependency selection, app registry responses, lifecycle hooks, and workspace data paths must preserve the distinction so one workspace can bind a public app, fork, or alternate provider under a distinct local id.

The installation-level `/apps` directory is the server-managed app store and trusted artifact cache.

It may contain built-in apps, commercial sealed apps, source-available store apps, and validated app bundles.

Remote catalog ingestion is still a core app-hosting responsibility. The official public catalog defaults to `https://maverick-app-store.versy.ai` and may be overridden per installation with `MAVERICK_APP_STORE_URL`. The app-store UI may request installation or uninstall for selected workspaces, but the core must own the authenticated operation that downloads a remote bundle, verifies its checksum, stages it under `apps/_bundles/<app_id>/<version>/`, registers the source as an `external_bundle`, creates workspace bindings for the authorized target workspaces, reports current workspace installation state, reports installation-level server app sources whether or not they are installed in the current workspace, installs already-registered server app sources into selected workspaces without copying source into the workspace, reports workspace-local app projects for the selected workspace context, and removes bindings during uninstall without deleting app-owned data.

The workspace-level `workspaces/<workspace_id>/apps/` directory is editable workspace material.

It should contain only workspace-created apps and explicit workspace-local forks of store apps.

Installing a store app into a workspace should create a binding to the store artifact by default.

It should not copy source into the workspace unless the distribution contract allows forking and the user or an authorized agent requests customization.

The core app-hosting domain should model at least these distribution modes:

- sealed
- source-available
- workspace-local

Promotion of a workspace-local app into an installation-level app is a core app-hosting operation, not an app-owned behavior. The initial promotion path is admin-only, copies the workspace-local source tree into `apps/<app_id>/`, rewrites only the copied contract's distribution declaration to `sealed` or `source_available/forkable`, registers the copied app as a `platform` source, and leaves the workspace-local project unchanged. The control plane must also persist ownership lineage: the workspace-local project creator becomes the promoted app owner for that `app_id`, later promotions of the same `app_id` are treated as owner-only updates, and a fork that wants to publish independently must use a different `app_id`.

This lets the core host closed commercial apps, open-source store apps, and fully local agent-created apps without changing the app surface model.

Implementation files in `core/apps/` should keep lifecycle responsibilities separate.

Recommended split:

- `registration.py` owns app source and workspace-local project registration
- `remote_store.py` owns remote catalog bundle staging and authenticated install orchestration
- `forks.py` owns workspace-local fork creation and provenance
- `installation.py` owns initial store and workspace-local app installation
- `status.py` owns enable, disable, uninstall, and purge transitions
- `reinstall.py` owns reattachment and import-recovery style reactivation
- `upgrades.py` owns upgrade, migration, rollback, and explicit rebase semantics
- `hook_payloads.py` owns canonical lifecycle hook context construction
- `health.py` owns app health probe execution
- `contracts.py` may remain a small public facade over contract builders, parser, serializer, records, and validation modules

`service.py` may remain as a public app-hosting facade, but it should not contain full lifecycle implementation.

### 4. Runtime orchestration

The core owns the generic runtime model for agent execution.

This includes:

- runtime lifecycle
- turn execution
- message delivery to runtime
- runtime status updates
- execution state transitions
- orchestration of tool execution
- process lifecycle
- runtime sessions that can carry an app-provided materialized `system_prompt`
- runtime sessions that can carry selected `skill_ids` when an agent type narrows the workspace default
- runtime sessions that can carry the selected `skill.catalog` provider app id used to resolve those `skill_ids`
- runtime sessions that can identify the app surface that created them with `source_app_id`
- runtime sessions that distinguish root chat sessions from hidden inter-agent participants with `session_kind`
- runtime sessions that control whether they may produce a user-visible runtime thread with `thread_visibility`
- runtime turns that can carry structured app references when an app UI parses human-facing mention text; `type: "app"` references carry a stable `app_id`, while `type: "entity"` references carry `app_id`, `entity_type`, `entity_id`, and optional safe label, summary, existence, and deep-link metadata

These fields are generic runtime configuration. They are not an Agents app dependency.

An app such as `agents` may compose prompt text and pass it to the runtime session creation surface, but the core must not parse app-owned role files or know agent type semantics.

The core does not define workspace-specific agent personas as built-in runtime types.

### 4A. Durable job execution

The core owns the app-agnostic `compute.job.execution` version `1` capability
for typed work that must outlive an HTTP request, app entrypoint, or runtime
turn. Its canonical envelope is `app-job.v1`.

The capability owns durable submission and idempotency, grants and budgets,
workspace quotas and fair scheduling, lease/heartbeat fencing, typed progress,
cooperative and operator-forced cancellation, retry/backoff, restart recovery,
executor advertisement and selection, bounded redacted logs, state events, and
assignment audit. It does not own app handlers or app business data.

The default JSON and optional Mongo control-plane adapters persist the same job
records through a storage-agnostic domain store. The server executor invokes
only explicitly registered, process-safe handler callables in bounded child
processes; the generic domain does not construct shell strings or interpret app
parameters as code. Input validation and output publication are delegated only
through explicit trusted provider-interface registries and fail closed when the
matching provider is absent. The complete contract and trust boundary are
documented in
`docs/architecture/durable_job_execution.md`.

### 5. Inter-agent communication

The core owns the infrastructure that allows multiple agents to coordinate.

This includes:

- delegation delivery
- inter-agent message transport
- status propagation between agents
- coordination queues and retries
- delivery reconciliation
- cross-agent operational routing

This is a core product capability, not an app concern.

The first concrete inter-agent domain lives under `core/inter_agent/`. It owns
schema-level run, participant, edge, approval, budget policy, budget ledger, and
normalized event contracts before any executor or child runtime session is
introduced. Its local JSON persistence is intentionally separate from
`RuntimeCollections`: records are workspace-scoped under
`workspaces/<workspace_id>/runtime/inter_agent/`, and replayable graph events are
partitioned per run under `runtime/inter_agent/runs/<run_id>/events.json`.

`inter_agent` events are a projection for graph mode and audit, not replacements
for runtime turn or process events. They carry per-run sequence numbers,
idempotency keys, correlation ids, and one of `summary`, `detail`, or `debug`
visibility. Server-side replay must treat those visibility planes as an
authorization ceiling: `summary` sees only summary events, `detail` sees summary
and detail, and `debug` sees all three planes. Event retention is also per
visibility plane so debug history can be shorter than user-facing summaries.
The bounded UI/audit timeline is not the scheduler recovery source by itself.
State-bearing orchestrated-run events for plans, control decisions and their
application, task definitions/results/retries, handoffs, and directive delivery
form a protected recovery ledger inside the run partition. Those records remain
until the run is deleted, are excluded from visibility-history pruning, and are
read by an internal allowlisted replay path that paginates to the beginning.
If a pre-ledger or corrupted run has a terminal task participant without its
result record, recovery fails closed instead of scheduling that task again.
F5 exposes the same replay contract to Chat graph mode through
`WS /ws/inter-agent/runs/<run_id>` and
`GET /api/inter-agent/runs/<run_id>/artifacts`; both surfaces cap
`summary`/`detail`/`debug` server-side by caller authority and run visibility.

The policy-aware runtime bridge lets core inter-agent services spawn a declared
`child_runtime_session` participant into a hidden
`session_kind=inter_agent_participant` runtime session, send turns to that child,
wait, interrupt, resume, close, and recover runs. The low-level native executors
for `manager_tools`, `sequential`, and `concurrent` remain operator and internal
surfaces. Deterministic synthetic participants are limited to tests or explicit
operator-controlled execution; public HTTP cannot supply controlled output.

Chat product orchestration uses the separate `orchestrated` mode. After the
normal generalist turn is accepted, Chat sends only the root session, source
turn, product policy, and idempotency key to
`POST /api/inter-agent/orchestrations`. Core creates a real hidden child
orchestrator as the only initial board participant. That orchestrator produces a
structured plan; core then materializes workers and edges dynamically, schedules
dependency-ready work under the concurrency budget, runs bounded
implementer/reviewer revision loops, and accepts completion only when an
approved final review covers the latest completed material frontier of the DAG
and causally supersedes every unresolved negative or malformed review.
Orchestrator-authored task ids cannot collide with reserved participant
identities. Persisted task participants are reusable only when their hidden
agent execution mode, label,
agent type, task-bound immutable snapshot digest, skills, and provider material
still match the task.
Control decisions use separate persisted `recorded` and `applied` events so
restart recovery replays cancellation, materialization, quality, and completion
effects before scheduling work. Persisted participants are recovered from their
immutable snapshots without re-resolving the agent catalog. Root-generalist
runtime updates become bounded directives in the inter-agent event store.
Every scheduler owner is bound to the run's persisted `recovery_generation`.
Planning/running/failure transitions, plan and control records, task
materialization, task claim/finalization, directive delivery, and completion
commit are status-and-generation conditional under the workspace transition
lock. A pause therefore fences already queued futures as well as active child
session creation: stale work cannot mark a participant running, overwrite a
persisted cancellation, or move the run from `paused` to `completed`. The pause
transition snapshots participants before releasing that lock, so a task claim
cannot fall between pause persistence and interrupt reconciliation. Runtime turn
queueing is enclosed by the same fence: a queued turn is either visible to the
interrupt or is never persisted and never dispatched. Worker activation is a
separate persisted compare-and-set under a cross-process runtime-session
lifecycle handoff: it rereads the authoritative turn and session, accepts only
`queued` turns on executable sessions, and never writes caller snapshots back
as lifecycle state. Activation alone does not authorize a later provider call.
Synchronous and asynchronous plain-hosted and agentic dispatch reacquire that
session handoff for a final authoritative `active`/executable check and retain it
only through the provider's acceptance callback. An interrupt that wins first
therefore prevents provider start; one ordered after acceptance can observe and
interrupt the accepted provider turn. Plain-hosted dispatch registers a
process-local cancellation handle before releasing that callback. Its interrupt
path first persists the terminal turn after the acceptance handoff, then
reissues provider cancellation and waits for the HTTP request to unwind, so a
stopped session cannot retain a live hosted request. Prewarm uses the same
session-only start handoff. Provider, provider-thread, visibility, and routing
metadata use an allowlisted partial store mutation under that handoff, so a
callback or worker return can never write stale status, timestamps, or other
lifecycle fields.
Interrupt and resume also share one cross-process run-control
handoff for the complete participant/session cleanup. Interrupt cancellation is
conditional on the recovery generation, runtime session, and task captured by
the pause snapshot, and resume advances the generation only after that cleanup
releases ownership and before a replacement scheduler may mutate the run.

Participant, tool, task, summary, and final-answer events are never written to
the root runtime store. The normal Chat transcript belongs exclusively to the
generalist. Agent nodes consumes run detail, inter-agent replay, artifacts,
approvals, and the bounded participant transcript endpoint; participant
transcripts and orchestrator completion answers remain inside that board.
Before a linked root-session turn is dispatched to its provider, core attaches
the same authorized bounded status/task/progress/quality/artifact projection
exposed by `GET /api/inter-agent/generalist-context`; the stored root transcript
still contains only the original user and generalist messages. Both synchronous
and asynchronous dispatch apply this composition for plain-hosted Chat and
agentic runtime sessions.

Those surfaces must materialize prompt, skill ids, skill catalog, source app,
owner, creator, and grants only from core policy or authorized materialized
snapshots; public HTTP, CLI, and MCP payloads must not mint those
authority-bearing values. Public run creation derives `source_app_id` from the
root runtime session, and public spawn ignores payload prompt, skill, catalog,
source-app, provider, snapshot, and operation grant fields. The bridge and
native executor must not clone authority-bearing prompt, skills, owner, grants,
or secret access from the root runtime session.

Root runtime sessions are also authority-bearing. Non-operator callers may attach
an inter-agent run to a root session only when they own that root, are
workspace/platform admin, or hold an explicit platform-minted `inter_agent_root`
grant; workspace membership alone is not sufficient. Child runtime session ids
are path-bearing ids and must validate as safe basenames before any runtime root
is created or deleted. CLI and MCP inter-agent close operations must receive the
same full platform cleanup state as HTTP so hidden child runtime roots, app
cleanup metadata, and thread cleanup events follow the official cleanup path.
Inter-agent run detail and event replay are also authority-bearing. HTTP run
detail, run listing entries, and event replay beyond the caller's capped plane
must require run creator, root-session owner, workspace/platform admin, operator,
or explicit `inter_agent_root` grant authority; workspace membership alone is not
enough to read another user's operational detail. Event replay must cap the
served `summary`/`detail`/`debug` plane server-side by both caller authority and
the run's visibility level.
Budget ledger recovery must also remain tolerant of active runs created before
participant-attributed turn reservations: idempotent retries of legacy
reservations and matching `inter_agent.budget.reserved` events without
`participant_id` must still match, and those consumed turns must not be ignored
by per-participant limits.

The F1 store contract is workspace-safe by default. Normal reads and writes must
carry `workspace_id`; operator-wide scans, if needed later, must be explicit
operator methods rather than fallbacks inside ordinary run/event APIs.
Participant identity is local to a run, so the persistence key is
`(workspace_id, run_id, participant_id)`, not a global `participant_id`.

Idempotent F1 operations must compare canonical fingerprints, not only ids. A
`create_run` retry with the same workspace idempotency key returns the existing
run only when the validated run spec fingerprint matches; mismatches fail as
idempotency conflicts. Event append and budget reservation retries likewise
compare their canonical payload envelopes. Budget reservation release is
idempotent. F2 treats participant/concurrency reservations as releasable runtime
work reservations, but successfully submitted turns remain consumed in the run
ledger so `max_total_turns` is enforced across repeated message sends.

`create_run` materialization must be retry-repairable on the JSON store. The
run record is the visible root and should be written only after the dependent
policy, ledger, retention, participant, edge, and initial event records have
been materialized. Generated ids inside an idempotent create bundle must be
stable for the validated spec so a retry can complete the same bundle, dedupe
initial events, and repair missing records without resetting an existing budget
ledger. This is the F1 recovery boundary; a durable event idempotency index
beyond event retention is intentionally deferred until a later runtime/API phase
requires that guarantee.

Agents materialization is recoverable at F1. When a participant includes a
materialized Agents snapshot, the participant record stores both the stable
digest and a core-owned copy of the snapshot payload so replay and startup
recovery do not depend on a mutable future Agents app record.

### 6. AI provider management

The core owns the abstraction layer for model providers and model backends.

This includes:

- provider definitions
- provider credentials and secret bindings
- provider capability metadata
- model selection contracts
- runtime adapter selection

`Codex` is one supported runtime backend, not the architectural definition of the core itself.

Provider definitions distinguish the technical provider kind from the role that
the provider plays in Maverick:

- `runtime_engine` providers own a runtime or agent loop and may expose runtime
  adapters.
- `model_provider` providers expose hosted or remote inference capabilities such
  as text generation without owning the runtime loop.
- `speech_provider` providers expose remote speech capabilities as governable
  metadata until a speech execution pipeline consumes them through official
  core/app surfaces.

The capability metadata must be modality-aware and conservative. Runtime
selection remains separate from model routing: hosted model providers such as a
low-latency text API must not be configured through the workspace runtime
backend selection path unless they also implement a runtime engine contract.

The system must be designed so that other backends and model providers can be supported without changing the app model.

The core must also be installable and bootable with no AI provider configured or available.

No provider is a valid initial platform state, not an installation failure.

Provider selection is an explicit later setup or admin action. Once configured, the persisted provider selection is the authoritative runtime backend choice for runtime turns, provider status, and recovery automation.

Provider status APIs should represent this state directly:

- `active_provider: null` when no provider is configured or the configured provider is unavailable
- a stable `blocked_reason`, such as `no_provider_configured` or `provider_unavailable`
- enough available-provider metadata for an authorized setup flow to choose a provider later

Runtime creation, turn execution, and recovery work that need an AI backend should fail on use with a recoverable provider-status error when no provider is configured. They must not silently fall back to Codex or any other first registered adapter.

Runtime-style providers must preserve conversation continuity inside a runtime session.

For Codex specifically, the core must use the Codex app-server protocol, not one-off `codex exec` calls.

The Codex adapter should own the provider-specific protocol:

- start one local `codex app-server --listen stdio://` process for the runtime session
- initialize the app-server process
- prepare a session-local `CODEX_HOME` under the runtime root before launch
- populate that runtime home from a configurable operator Codex home, using `MAVERICK_CODEX_HOME`, `CODEX_HOME`, or the current user's default Codex home
- copy only required identity and configuration material into the runtime home, such as Codex auth, version, installation identity, sanitized config, and rules
- avoid hardcoded host paths for Codex identity or configuration
- keep runtime skills materialized separately through the selected workspace `skill.catalog` provider's data rather than loading user-global or core-bundled skills into every runtime
- create a persistent Codex thread with `thread/start` when no provider thread exists
- resume the existing Codex thread with `thread/resume` when a runtime session already has a provider thread id
- submit each user turn with `turn/start` against the same provider thread id
- admit later user messages into a regular active turn with `turn/steer`, including a stable client message id, only when the adapter declares same-turn input support and the Maverick turn is still correlated to the expected provider turn id
- interrupt active work with the provider's turn interrupt method
- keep the provider thread id as provider-runtime state, not as chat-app state
- keep the local provider process warm for a short idle TTL after a terminal turn, then terminate it if the runtime session still has no queued or active turns, while keeping the provider thread id so a later turn can restart the backend and resume the same conversation

On Linux systemd deployments, the core host should carry a negative OOM score
adjustment so the platform control plane is less likely to be terminated during
host memory pressure. Runtime provider processes must be reset to neutral OOM
priority when launched. They must not receive a positive adjustment: doing so
causes early-OOM daemons to terminate every active session before selecting the
process that is actually consuming the most memory.

The core runtime session remains the Maverick-owned lifecycle container.

The provider thread is the selected backend's conversation container.

Those two ids are intentionally different but must be linked by the core runtime state so a chat can be reopened, a browser can refresh, and the next turn still reaches the same provider conversation.

The core also owns the workspace chat thread catalog that points at runtime sessions.

A chat thread is the user-visible runtime conversation record. It stores the thread id, linked `runtime_session_id`, title, availability, source app metadata, optional project id, and `last_user_message_at` timestamp. Apps such as `chat` may render or update that record through core runtime APIs, but they must not persist a second app-owned thread catalog or delete runtime sessions themselves. The core runtime owns availability transitions: queued user turns mark the linked thread as `queued`, started turns mark it as `active`, and terminal turn outcomes or interrupts mark it as `free`. A user message admitted into the active turn updates recency without changing that turn's active availability. Thread catalog reads reconcile availability from runtime turns while accepted message events preserve the newer same-turn user-message timestamp.

Chat may pre-create one hidden `chat_root` through `prepare_only`. Core keys that
prepared aggregate by workspace, owner, and a persisted hash of the normalized
session configuration; exact repeated or concurrent requests return the same
`session_id` even while provider prewarm is pending. The first accepted turn
promotes that same aggregate to `thread_visibility=user` and clears its prepared
fingerprint. A periodic bounded worker converges each workspace-owner pool to at
most two distinct prepared configurations, removes exact duplicates and entries
older than 30 minutes, and always invokes the canonical full runtime cleanup path.
Its selection and cleanup revalidate under the session lifecycle handoff and
exclude user-visible sessions, sessions with turns, and
`inter_agent_participant` sessions.

The runtime thread catalog uses bounded payload shapes. `GET /api/runtime/threads` returns a recency-sorted page and accepts a bounded metadata query so shell search surfaces can backfill matching older threads. The initial `runtime.thread.snapshot` WebSocket frame returns the complete user-visible catalog as lightweight summary records, with `threads_page` metadata reporting that the snapshot has no remaining page. Mutating thread APIs return only the changed thread or removed ids plus a page hint; they must not reattach a full thread catalog to create, rename, read-receipt, delete, or clear responses.

Agents read completed or active user-visible conversations through the core-owned
read-only CLI/MCP surfaces `core.runtime.threads.list`,
`core.runtime.transcript.read`, and
`core.runtime.transcript.message.read`. These surfaces are a safe message
projection, not access to raw runtime events or session files. The catalog
filters authorization before metadata search and pagination. Transcript reads
use only the paged append-only event-history contract, capture physical append
positions for both events and eligible turn-input fallbacks in one opaque
`snapshot_cursor`, return stable message ids and explicit projection warnings,
and use character-window continuation for long messages. Event ordering by
`(created_at, event_id)` happens only after the immutable append boundary is
applied, so retroactively timestamped events cannot enter an older snapshot.
Turn records admitted before the turn boundary may supply missing user input,
whose submission fields (`input_text`, client message id, creation time, and
runtime mode) remain immutable across lifecycle updates. Mutable terminal state
is never used by historical reads; every such input fallback produces a warning
and makes `projection_complete` false. Empty event
or turn positions are represented inside the same cursor and remain empty on
replay after later writes. Returned conversation content is labeled
`untrusted_conversation_data`; system/developer prompts, provider payloads and
thread ids, runtime paths, environments, and raw tool output are not part of
the default `messages` profile. Structured payload keys are canonicalized
before sensitive-field filtering and share one global node/serialized-byte
budget; truncation is explicit through structured-content completeness fields.

Transcript authority is independent from execution mode. The target must remain
a `thread_visibility=user` session in the caller's workspace, and the caller
must be its owner, a workspace/platform admin, or hold a platform-minted
`read_transcript` grant as the user or calling runtime session. Hidden
`inter_agent_participant` sessions remain available only through their existing
participant-transcript projection. Every allowed or denied transcript read is
audited without conversation text; audit payloads contain only caller/target
identifiers, authorization relation, profile, page/window counts, redaction
state, and outcome.

### 7. Execution policy

The core owns:

- sandbox policy
- full-access policy
- runtime execution mode enforcement
- workspace execution boundary enforcement
- network egress policy primitives for sidecars and app-owned network work

The workspace domain may declare metadata and governance state, but the effective runtime mode must still be resolved by `execution_policy/`.

For the `default` workspace, the effective runtime mode is `full-access` by default when both platform policy and workspace governance allow it.

For non-default workspaces, the effective runtime mode remains sandbox-only regardless of runtime request.

Browser-controlled network work uses the core-owned `egress/` domain before navigation and after redirects. P0 browser egress is fail-closed: only `http` and `https` URLs are eligible, private, loopback, link-local, Docker bridge, host-gateway, and metadata endpoints are denied beneath DNS names, and local Maverick development targets such as `http://hostmachine:8000` require an explicit admin-enabled dev exception.

Hosted agentic runtimes use one Core-owned sequential loop. Provider clients are
codec/transport boundaries only; they do not own budgets, tool registries,
confirmation, retry, egress, or recovery policy. The loop refreshes effective
authority before each request and side effect, journals request identity before
acceptance, and routes every tool through the existing CLI/MCP/app-interface/Core
catalog and encrypted invocation ledger. Provider-private protocol bytes remain
behind the matching codec service and public events are bounded, normalized,
and private-field-free.

Before egress, that loop compiles a Core-owned semantic-envelope schema. Its
ordered blocks preserve platform, runtime/capability, workspace, agent, user,
governed-context, attachment, app-reference, skill, tool, result, and
provider-state provenance instead of flattening them into one prompt. The
runtime resolves the complete root-to-workdir `AGENTS.md` chain and complete
invoked `SKILL.md` documents through descriptor-confined, version-fenced reads
on every provider step, including continuation and recovery. A canonical source
snapshot digest and a distinct compiler/version-bound destination projection
digest are persisted in the provider-step journal. Provider codecs may render
roles differently only through their certified deterministic projection; they
may not omit a mandatory block or infer authority from instructions.

Context-window admission evaluates the complete prepared request, not only the
provider-private history. If history is below its ordinary trigger but the
current user/tool/schema payload would consume the independent reserve, Core
performs at most one forced, recipe-bound history compaction, rebuilds the
request with new evidence, and validates it again. A second overflow fails
closed before transport.

Each hosted request reserves its conservative provider price ceiling before
transport. When that request reports priced usage, Core replaces only the
active reservation with the reported cost before considering the next step;
if priced usage is absent, the worst-case reservation remains consumed. This
keeps every next request safe against the turn ceiling without charging the
maximum possible output repeatedly after low-cost tool steps.

Textual tool results may contain absolute host paths as untrusted document
content. Egress first rewrites the exact workspace root to its
`workspace://<workspace_id>` identity, then redacts any remaining recognized
host path before remote export when the policy permits sensitive transforms.
The same remaining host path in user input, platform instructions, schemas, or
provider state is still denied; path redaction never changes the allowed data
class, provider, or upstream decision.

The runtime adapter artifact digest covers the concrete adapter plus every
declared operational class, function, and module for the shared loop and the
installed provider codecs. Digest construction reads each resolved source file
directly; it must never collapse a function to the built-in `function` type.
Changing any declared codec, request builder, stream consumer, tool
orchestrator, or filesystem module therefore invalidates the previous
certificate at runtime.

Sequential provider requests must explicitly disable parallel tool calls when
the selected endpoint declares that control. If it does not, the request omits
the unsupported parameter. The decoder retains every coherent indexed call;
the preliminary ledger persists each call before resolution and the shared
loop returns a durable `parallel_denied` result for every call without crossing
an effect boundary. No secondary call may be silently discarded. One
OpenAI-compatible tool call may be preceded by provisional assistant text; the
codec keeps that text only in provider-private continuation state with the
assistant tool call, executes the single call through the shared loop, and does
not publish the provisional text as final output. Invalid or conflicting
tool-call identities and indices remain fail-closed conditions.

The provider-step journal is the continuation authority. A ready pairing can be
used only by its original active turn and requires the exact source journal,
turn, provider request, private-state generation, and non-tool input-lineage
digest. Queue, token, prepare, continuation, and execute gates read persisted
journal state. A normal new user turn cannot inherit a pairing or have its input
silently ignored. Terminal limits, cancellation, authority/certificate
revocation, egress denial, and execution failure must complete certified
same-turn recovery or quarantine the pairing.

Quarantine persists the allowlisted `recovery_required` session reason before
best-effort private diagnostic detail, with bounded reread/retry for session and
journal CAS. Diagnostic, audit, private-payload, or runtime-state projection
failure cannot restore execution authority; a session CAS remains sufficient
containment when the journal cannot be advanced.

Final hosted text is encrypted into a deterministic Core-private outbox before
the provider journal may complete or commit. The journal keeps only identity,
digest, size, and separate output/completion delivery acknowledgements. Stable
terminal event ids allow startup or same-turn retry to deliver the same output
once without another provider request; an unprovable output is quarantined and
never regenerated. Final text is absent from the journal and unauthorized APIs.

Agentic execution failures cross the runtime boundary as a stable reason code,
a mapped redaction-safe public message, and an optional bounded diagnostic
reference. `runtime.turn.failed` persists those fields; numeric process exit
codes remain diagnostics and are never the sole user-facing error.

Execution-policy-owned workspace filesystem discovery is a separate read-only
Core capability from file reads. `core-capability:filesystem.list` returns only
bounded, deterministically ordered relative paths and entry types, limits depth
and result count, never returns file content, never follows directory symlinks,
and resolves its requested root inside the workspace boundary. Recursive
traversal opens the root and every child descriptor-relative with
`O_NOFOLLOW | O_DIRECTORY`; it never reopens a verified child by pathname, so a
concurrent directory-to-symlink swap fails closed. Certification and policy
must attest and grant listing independently from
`core-capability:filesystem.read`.

The code-owned Full Workspace Agent Contract is an atomic revisioned claim,
not a menu of product tiers. Its Codex-derived baseline requires the complete
workspace instruction, list/search/chunked-read, create/replace/edit/patch,
move/delete, confined shell, managed process, CLI-discovery/invocation, and
MCP-discovery/invocation handle set together with skills, file attachments,
app references, confirmations, interrupt, and recovery capabilities. Profile,
certificate, immutable execution binding, and every live authority refresh
must retain the same contract revision. Losing one required live capability or
handle makes the agent unavailable; Core does not materialize a partial agent.
The claim also requires an executable result-policy gate plus successful
certification-suite behavior coverage for complete execution, exact-byte
classification, egress/error pairing, post-image/read-after-write behavior,
and pre-effect guarantees across create, replace, edit, patch, move, delete,
shell/process, and CLI/MCP scenarios. A declared mode string or the mere
presence of a handle is not evidence. Hosted candidates whose gate is
incomplete must omit the Full Workspace revision and use the distinct
`maverick_agent_candidate` family; `maverick_agent` is invalid without the
complete atomic contract. The current Google revision 37 and OpenRouter
revision 36 definitions make that atomic claim only because the executable
gate returns all 21 required result behaviors, including real app-owned
CLI/MCP reads with Core-audited conservative effect metadata and executable
closure bytes, a real inter-agent CLI-create/MCP-wait workflow with bounded
public result projections, raw/base64/chunk marker
narrowing, revoke-then-rebuild, delayed-egress-after-revocation, transport
revocation before the first and every subsequent provider-stream advance,
overlay-commit rollback, and immutable shell/process workspace-snapshot probes
that race post-spawn `.git` creation and rename. They remain
uncertified, unbound, contained previews rather than a release authorization.

Hosted filesystem mutations are descriptor-relative and version-fenced.
Replacement uses Linux atomic exchange/no-replace primitives so a final-entry
swap cannot overwrite an unobserved inode. Recursive deletion first validates
the bounded tree, then atomically moves the exact top-level inode into a
platform-only quarantine before descriptor-only cleanup. Search cursors bind a
complete revalidated snapshot, query, scope, and pagination position. Every
mutation re-resolves the applicable root-to-target `AGENTS.md` chain and can
bind the caller-observed instruction-scope digest before crossing the effect
boundary.

Direct content replacement clones and verifies the pre-image mode, ownership,
and bounded ACL/xattr set before exchange. A version-bound classification on
the exact pre-image is monotonically rebound to the exact post-image and later
read-after-write observation. The successful mutation's private session-ledger
result carries the exact identity/revision/digest and reconstructs that lineage
when the hosted loop builds its next filesystem orchestrator; move rebinds it
to the destination. A created file remains unclassified without authoritative
source taint or an active explicit runtime-public classification policy, and any
out-of-band version change invalidates the transient lineage. Failed writes
remove only the empty, identity-matching parents they created. Move validates
the exact source before opening or creating the destination chain and removes
new destination parents after a successful rollback.

Mutable classification authority is carried as an exact id/kind/ref/revision/
digest/policy tuple on canonical sources, durable tool records, semantic
metadata, and encrypted provider-state envelopes. Original and projected
filesystem, instruction, search, shell, process, CLI, and MCP result bytes are
scanned before persistence, and marker detection may only make the class more
restrictive. Reconstructed filesystem lineage, delayed tool pairing, semantic
reuse, provider continuation, and final egress all revalidate the exact current
authority tuple. Legacy, partial, changed, or revoked lineage becomes
`unclassified`. A runtime-public issue/revoke record is authoritative only when
its deterministic audit evidence is present, so an audit write failure cannot
publish the mutation.

Hosted shell commands stage a descriptor-confined immutable view at the fixed
`/workspace` sandbox identity; they never bind the live workspace namespace
into the sandbox. A caller that
needs persistent command effects declares a bounded set of directory scopes and
the exact `AGENTS.md` digest observed for each; the command runs against a
private overlay. Core scans the complete bounded upper diff, rejects undeclared
paths, instruction-file, non-UTF-8, deletion, symlink, newly-created directory,
hardlink, and unsupported metadata effects. Ordinary xattrs, ownership/mode
changes, metadata-only timestamps, and mutations of directory or overlay-root
metadata are compared against descriptor-confined live or pre-execution
metadata and rejected rather than silently discarded. File atime/mtime attached
to an actual content create/replacement are representable and are materialized
exactly, so read-modify-write editors and read-after-write tools retain their
filesystem semantics. For a content replacement, the transaction clones and
verifies the existing file's mode, ownership, ACL/xattr set; representable new
file mode/ownership is applied explicitly. Existing or upper-layer link counts
greater than one are rejected so Core never silently splits an inode relation.
Core then re-resolves the instructions for every changed file. All UTF-8
creates/replacements are staged in one private transaction and committed with
retained pre-images. Each pre-image remains descriptor-pinned, its complete
metadata/xattr snapshot is checked immediately before exchange, and every
retained preservable field is checked again afterward; a failure or late race
rolls the entire batch back in reverse order before any failure is reported. A
root digest therefore cannot authorize a change governed by a nested
`AGENTS.md`, and a rejected multi-file diff cannot leave an earlier file
committed or erase a concurrent metadata change. Bubblewrap consumes the
retained snapshot descriptor while constructing the read-only/overlay mount and
closes it before target `exec`, so the command cannot bypass the mount with
`openat(2)`. Managed processes retain
the same private overlay until a successful terminal status. Terminal
`process.status` is conservatively a mutating, non-retry-safe capability because
it commits that overlay; commit failure crosses the mutation boundary and is
reported with ambiguous-execution semantics while the batch itself is restored.
Timeout, process failure, interrupt, or invalid diff discards the overlay.
Platform `runtime/` is replaced by an empty mount point. During the bounded
descriptor-relative, no-symlink staging traversal, Core omits every component
named `.git` regardless of its type and rejects unsupported entries, exhausted
limits, or concurrent namespace/content/metadata changes. The resulting
snapshot remains fixed for the whole shell or managed-process lifetime, so a
`.git` created or renamed in the live workspace after spawn cannot appear in
either read-only or private-overlay mode. HOME and TMP are ephemeral, host
absolute paths are not exposed, system
tooling is read-only, and the network namespace is disconnected. Synchronous output is drained under
a hard byte ceiling. Long commands use session-owned process handles with bounded streaming
output, stdin, interrupt, timeout, process-group cleanup, durable redacted
records, and the common orphan reaper. Cancellation is carried into synchronous
Core surfaces: shell and managed-process execution terminate complete process
groups, discard private overlays, and reach worker quiescence before the
cancelled turn is released. The hosted adapter owns its managed-process
registry; session close, explicit session termination, and idle reap finalize
live handles, output capture/FDs, overlays, the global process registry, and
durable terminal process status together.

Transient prompt, agent-instruction, and governed-context blocks are not public
by provenance. Production bootstrap always installs a closed Core-owned
capture writer before provider dispatch. It conservatively classifies the exact
prompt, agent instruction, reference metadata, and every governed-context
control, summary, task/result, and artifact chunk, then stores the complete
immutable manifest in the turn with one CAS. Detection of a sensitive marker
may only narrow the result; absence of a marker remains `unclassified` unless
an operator has issued the reserved CAS-revisioned runtime-public
classification policy. That policy is server-owned, self-digesting, revocable,
and revalidated at admission; it authorizes Core to emit a new classification
bound to the exact source identity, revision, canonical-byte digest, policy
revision, and authority record. It is not a browser declaration or a redaction
inference. Source ids and digests alone never select or widen a class. Governed
context restrictively joins those exact
entries and remains untrusted; a missing manifest, unknown source, changed byte,
or identity mismatch stays `unclassified`. Resource-returning tools propagate
the exact observed resource classification, and edit/patch diffs retain their
pre-image taint.

Variable hosted tool output is also conservatively classified from its exact
canonical bytes; marker absence remains `unclassified` without the same active
runtime-public authority or an exact resource/result contract.
Read-only shell/process streams and CLI/MCP discovery/read results retain the
complete payload through the common compactor. If their derived class is not
allowed remotely, Core keeps the private result and sends a public, call-id
paired `tool_result_egress_denied` error on the next provider request; it never
silently drops pairing or relabels the bytes. Core-owned CLI/MCP definitions
may provide an explicitly public result contract only when the definition,
schema, and certified TCB ownership all agree; app declarations cannot
self-promote. Shell and managed-process mutations execute first in the private
overlay, classify the exact bounded result and intended effect evidence, and
commit only after public-result admission. A denied result discards the
overlay, so the effect does not precede its egress guarantee. The hosted Full
Workspace claim is accepted only while the behavior probe covers every read and
mutating scenario. Generic serialization, hashing, redaction, or source
ownership never promotes content.

Every semantic-envelope classification is additionally bound to the SHA-256 of
the exact canonical bytes projected for that block. Composite sources use a
restrictive join over every independently classified component. Attachment
metadata is admitted separately from the referenced file and then joined;
neither a client-controlled name nor other metadata can inherit the file's
class. Skill catalogs preserve the lexical selected identity and reject a
symlinked catalog component, skill directory, or `SKILL.md`. Skill blocks then
project the complete descriptor-read `SKILL.md` itself and do not mix unbound
catalog/state metadata into its classification. A digest
mismatch is downgraded to `unclassified` before egress. Attachment-only turns
omit the semantically absent empty prompt block.

When a large result is replaced at request time by an artifact reference, its
semantic source digest is recomputed over the exact reference/summary bytes
shown to the provider. Data class, trust, source identity, and classification
revision continue to carry the original result taint separately; the original
payload digest remains the immutable private artifact identity.

Materialized app references have a separate resource-side classification. Core
derives a stable app/entity identity and an exact revision/digest from the
server-materialized reference, then the production `PlatformState` resolver
looks up the matching workspace resource-classification record. Missing or
mismatched records remain `unclassified`; app-reference metadata admission
cannot substitute for resource evidence or promote the reference to `public`.

CLI and MCP access uses four fixed certified Core wrappers: discovery returns
only definitions allowed by the authoritative registry invocation policy plus
a registry/session-bound invocation token; run/call requires that token and
re-enters the official runner, which rechecks current authority. Enabled app
surfaces and collaboration/inter-agent commands therefore remain app/Core
owned rather than being copied into a shadow registry. All tool results pass
through the same bounded result compactor used by the Codex route before
provider egress. Every installed app surface must declare a conservative
static effect class; a mixed surface may additionally declare one exact
top-level argument discriminator whose static class is the maximum severity of
all enumerated values. Omitted discriminator behavior is explicit, while an
unknown value, malformed nested argument payload, invalid declaration, or
missing declaration is `unclassified` and denied before execution. Read-only
app calls may proceed through the production wrapper only when their platform
source identity, live descriptor digest, reparsed metadata, and exact executable
closure digest match the Core-owned built-in effect audit. That closure includes
the entrypoint, descriptor, app contract, app-local backend, and any reviewed
extra executable dependency; the same paths are hashed by the certified TCB.
Core repeats this authority check immediately at dispatch, after validation and
confirmation, so code drift between catalog materialization and execution is
denied before the effect boundary. Workspace-local and external app descriptors
cannot self-authorize hosted execution. Exact result bytes still require
ordinary classification and egress admission; app-owned metadata cannot mint a
certified public-result contract or authorize a mutation. Website Studio's
`build_preview` and `preview_document` are consequently classified as
mutating, while persistent SQLite/file pre/post tests cover every remaining
Website Studio CLI/MCP read action.

Core-owned inter-agent CLI/MCP definitions declare their exact operation effect
instead of inheriting `unclassified`: create/spawn/send/execute/resume are
mutating, interrupt/close are destructive, and wait is read-only. Each is bound
to a reviewed result-projection contract that drops prompts, messages, events,
participant output, final answers, labels, cleanup reasons, and other content,
exposing only bounded lifecycle metadata, safe platform ids or hashed
references, counts, and booleans. A malformed result is replaced by a fixed
public failure projection rather than falling back to the original bytes. The
Full Workspace gate executes a production-composed CLI run creation followed by
an MCP wait and verifies discovery-token authority and projection pairing end to
end.

### 8. Secret management

The core owns:

- secret storage
- secret resolution
- secret bindings
- secret delivery to runtime under controlled conditions

The core does not allow apps to own the secret values themselves.

### 9. Recovery and operational safety

The core owns:

- runtime recovery
- failed-start recovery
- migration failure visibility
- operational health checks
- platform-safe error handling

### 10. Runtime interface

The core exposes the generic runtime-facing interface for:

- sending an agent message
- accepting a client-generated message id for idempotent UI reconciliation
- reading current turn state
- receiving turn updates
- receiving runtime events

This is infrastructure.

It is not the same thing as the chat domain.

### 11. Capability surfaces

The core owns its official platform-facing and operator-facing capability surfaces.

These include:

- `mcp/` for structured tool access
- `cli/` for local command-oriented operations

The core may also own:

- `skills/` for procedural guidance on using core capabilities correctly

These are not separate products.

`mcp/` and `cli/` are executable surfaces of the same core platform.

`skills/` is a non-executable instructional layer attached to those surfaces.

The same platform host framework should also be able to expose app-contributed MCP, CLI, and skill surfaces once those apps are installed and enabled.

Apps may expose reference tools through their declared MCP and CLI surfaces so other apps can link to app-owned records without reading app-private storage. The core's responsibility is generic: validate contracts, register enabled app surfaces, enforce workspace policy, invoke the declared entrypoints, and expose discovery metadata. The core must not know how to search business records, chat threads, storage files, memory nodes, or any other app-specific entity.

For authenticated mounted app frontends, the platform host exposes the generic HTTP surface `/api/app-references/manifest`, `/api/app-references/search`, `/api/app-references/resolve`, and `/api/app-references/summarize`. These routes discover enabled apps that declare `capabilities.reference_entities`, enforce the same visibility policy as mounted app surfaces, invoke the owning app's reference MCP tools, and normalize results into stable `type: "entity"` reference payloads. The core never reads app-owned storage to satisfy these requests.

Reference search aggregation must remain app-agnostic but should not let one provider's broad result set hide later enabled providers. The core builds one visible MCP registry and runner for the HTTP search request, reuses it across provider calls, and applies a short request-scoped reference-search timeout so typeahead-style UI can return available results instead of waiting for a slow provider. Direct MCP and CLI reference tool invocations keep the ordinary app MCP entrypoint budget unless their caller explicitly supplies a shorter invocation context. For non-empty queries, the core ranks normalized candidates by generic text relevance before applying the response limit. For empty picker requests, it interleaves candidates across provider/entity groups before truncation and may return once enough provider/entity groups have contributed to the response.

Runtime turn submissions treat client-supplied `app_references` as reference identities, not trusted provider context. Before the provider prompt is built, the core verifies that the app is enabled and visible in the workspace, resolves or summarizes entity references through the owning app's reference tools, and uses only owner-returned labels, summaries, and deep links. Unverified references are omitted rather than materialized from client-provided descriptive fields.

App-owned runtime launch requests may include Storage-backed `attachments` for the submitted turn. The app-hosting boundary validates these attachments before runtime submission: the field must be a list of objects with no more than five entries, each entry must name a `workspace_relative_path` or `relative_path` under `storage/uploaded/` or `storage/generated/`, absolute paths and `..` segments are rejected, optional `size_bytes` values must be numeric non-negative integers, and the referenced file must already exist in the workspace Storage tree. The core normalizes accepted attachments to workspace-relative Storage paths and passes them to the runtime turn submission path.

The common reference tool convention is:

- `<app_id>_reference_manifest`
- `<app_id>_reference_search`
- `<app_id>_reference_resolve`
- `<app_id>_reference_summarize`

CLI surfaces should mirror the same behavior with lightweight commands such as:

```text
<app_id> references manifest
<app_id> references search
<app_id> references resolve
<app_id> references summarize
```

Every app may expose at least a reference manifest. Apps with no referenceable entities should return an empty manifest rather than forcing the core or another app to infer that from missing app-specific behavior.

## What The Core Is Not

The core should not own:

- memory content
- chat content as a domain model
- business record content
- dynamic view content
- checklist content
- app-owned persisted records
- app-owned indices
- workspace-local app databases
- workspace-local app file structures
- agent persona definitions for a workspace

The core should also not force every operation through only one surface.

These belong to apps and workspaces, not to the core.

The core should also not be modeled as if it were a generic web app scaffold.

So the repository should not describe the core through names such as:

- `backend/`
- `runtime_backend/`
- `app/`

unless one of those names refers to a real product domain, which is not the case for the Maverick core.

Those names describe implementation posture, not product architecture.

## Core Versus Chat

The core should expose the runtime message and turn interface.

The chat app should own:

- persistent conversations
- thread model
- chat UI
- chat-specific organization
- chat-specific storage

So:

- runtime interaction = core
- chat domain = app

## Core As Platform Host

The public Maverick host should run the core, not one particular app.

In deployment terms, the intended model is:

- a public deployment hostname reaches the core platform host
- the core mounts enabled app surfaces
- the core enforces auth, workspace context, and policy before dispatching to app surfaces

This means the core is the host and orchestrator for apps, not the owner of the app domains themselves.

The core should be able to mount:

- app frontends
- app backends
- app MCP surfaces
- app CLI surfaces
- app skills
- app widget frontend surfaces

The platform should not force every app into the same UI or runtime style, but it should remain the owner of:

- routing
- policy
- mounting
- installation and enablement checks
- workspace-aware dispatch

Widget mounting follows the same platform-host rule.

An embeddable widget is not core UI and not direct app-to-app communication.

The core is responsible only for:

- validating widget declarations in app contracts
- exposing enabled widget metadata through the workspace app registry
- mounting widget frontend surfaces through controlled routes
- enforcing auth, workspace context, install state, and enablement before loading a widget
- providing deterministic routing metadata so host apps can find compatible widgets

The core must not:

- render chat widgets itself
- own widget business state
- let one app import another app's source tree
- special-case a specific widget owner inside the runtime or registry

For example, if chat embeds a checklist widget:

- chat owns the transcript host
- checklists owns the widget renderer and checklist data
- core owns registry, routing, auth, and workspace enablement

### PWA and browser-cache boundary

The platform host owns generic HTTP correctness, verified frontend-artifact
metadata, and a public fail-closed PWA rollout projection. It does not own app
read-model schemas or place app business payloads in browser storage.

The Base Shell owns the root service worker, verified static-cache lifecycle,
update coordination, its bootstrap loading/retry behavior, and the coordinated
cleanup protocol. It does not own a product mode or global UI for transport
reachability. Each app remains responsible for the classification,
sanitization, revision, TTL, size budget, invalidation, and ordinary loading
behavior of its own read models. Storage separately owns stable file identity
and an automatic bounded file cache. Shared browser mechanics may live in a
platform package, but that package must not import app models. Its client
capability is minted by the top-level host with one bound user/workspace/app
principal; embedded app options cannot select or replace that scope.

The SDK boundary is reinforced by browser-origin isolation. Core issues a
one-shot body-only launch ticket for every app or widget document and serves it
from an authenticated per-app, per-login-session host under the reserved
app-frame namespace. Direct non-shell app documents on the platform origin are
rejected; the Core-owned no-store OAuth callback relay contains no app bundle
and bootstraps the actual callback on the isolated origin. `allow-same-origin`
therefore preserves normal app behavior only
inside the app's distinct origin and does not expose shell-owned IndexedDB or
OPFS. The validated session propagates its canonical local and mount app ids as
internal HTTP and WebSocket scope authority. Every app or widget frontend path
must match that bound owner before routing; the proxy marker alone grants no
document authority. Base Shell validates both the exact registered frame window
and origin for inbound messages and never broadens host-to-frame delivery to `*`. The
default-off `data_cache` flag still enforces the separate resource, privacy,
and physical-rollout gates for M3.

This isolation boundary is mandatory. Core has no same-platform-origin app or
widget launch mode: invalid or unavailable isolated-origin routing fails the
launch closed and never makes direct documents available as a fallback. A
hosted deployment may terminate either a currently valid externally managed
`*.sidecars.<installation-domain>` wildcard or Core-managed exact certificates.
The latter uses HTTP-01 only for internally derived `sc-*` and `af-*` names,
batches every launchable app name for one login session into one SAN lineage,
publishes validated key pairs atomically for Nginx, and fails ticket issuance
until the exact host is ready. It does not accept a manually frozen list of
observed origins. Installer health checks exercise reserved hosts from both
families with normal hostname verification and require their distinct exact
unauthenticated-session errors before the hosted boundary is accepted.

Cache API, IndexedDB, and OPFS hold derived copies only. They cannot become a
source of platform authority or satisfy capability, certificate, provider
binding, admission, egress, recovery, confirmation, or revocation decisions.
Unknown classification and unavailable policy fail closed to network-only. The
normative policy mapping, rollout switches, transparent-cache behavior, and
transport recovery boundaries are recorded in
`docs/adr/0012-transparent-pwa-cache-and-network-resilience.md`.

The hosted binary-response contract has three private policies. Mutable files
use `private, no-cache` with a strong ETag and byte ranges. Explicit immutable
revisions use `private, max-age=31536000, immutable`; the app must provide the
stable ETag. Ephemeral responses, live generated audio, and temporary ZIPs use
`no-store`, and a `delete_after_send` response can never return `304`. Core
removes a `delete_after_send` file only after the complete GET body has been
iterated; HEAD and bodyless error/range responses leave it available for a
later GET. Core evaluates authorization before conditional validators,
applies weak matching to `If-None-Match`, and accepts `If-Range` only when
its strong ETag matches the current representation. JSON responses default
to `private, no-store` unless
their owner opts into a narrower explicit revalidation contract.

Base Shell's M2R production build uses the verified
`maverick.frontend-assets.v2` manifest. Its `navigation_fallback` names the
normal HTML entrypoint, and each `precache` record contains the public URL,
artifact path, SHA-256 digest, and exact decoded byte length. Its build identity
covers the Rollup graph, service-worker template, navigation fallback, and
selected precache map; the worker is then generated from that identity. Core
refuses undeclared, mismatched, ambiguous, traversal, API, WebSocket, backend,
sidecar, and worker precache URLs before hosting the app. There is no manifest
alias for the superseded fallback-document field.

The root worker owns only these Cache API namespaces:

- `maverick-static-v2:<build_id>` for an atomically installed, verified shell;
- the exact legacy `maverick-app-static-v2` and `maverick-base-shell-v3` names
  solely for bounded migration cleanup.

App and widget documents run on an isolated origin and therefore are not
controlled clients of the shell-origin service worker. Core rewrites generated
HTML `src` and `href` references below `/apps/<app_id>/assets/` to the exact
public platform origin. Vite builds that emit asset URLs from JavaScript use the
shared isolated-frame URL plugin: HTML and CSS retain the public app mount,
while lazy-preload dependencies, workers, and imported media are emitted
relative to the JavaScript module (`import.meta.url`). Because that module was
loaded from the platform origin, runtime-created URLs cannot fall back to the
isolated document origin. Safe build outputs such as `.mjs`, audio/video, font,
PDF, and `.wasm` assets may be read cross-origin without a platform cookie;
source-like files and maps remain private. Those requests use the browser HTTP
cache, not a shell Cache API namespace: Core preserves compression, emits the
public CORS/CORP contract, and grants one-year immutable caching only to bytes
verified against the app's frontend manifest. The obsolete
`maverick-app-static-v2` runtime path must not be presented as the normal
app-loading cache.

Navigation is network-first with a bounded timeout. Only `/`, `/app`, and
`/app/...` may fall back to the verified normal Base Shell entrypoint. Other
navigations keep ordinary browser/network behavior and receive no alternative
product document or synthetic response from the worker. Generated immutable
shell assets are cache-first only after digest and size verification. Other
pre-cached public assets are revalidated and fall back only to matching
verified bytes. Public app bundles and API, SSE, WebSocket, backend, sidecar,
service-worker, non-GET, cross-origin, and range requests are never answered by
the worker.

Install failure deletes only the incomplete cache for the candidate build and
leaves the active build untouched. A waiting worker activates through its
normal lifecycle or an explicit release action that is independent from
transport state; controller change reloads already controlled clients so an
old shell does not continue under an incompatible worker. Activation removes
only obsolete known shell-cache names, including the two exact legacy names,
never IndexedDB, OPFS, or unrelated Cache API entries. Kill-switch cleanup uses
the same bounded names and unregisters the root worker, while recovery repairs
missing or corrupt entries in place without discarding entries that still
verify.

Transport recovery is an internal RAM-only mechanism, not a render authority.
Browser `online`, focus, and visibility events are retry hints; a Maverick
response confirms useful transport. Idempotent reads may retry with
single-flight execution, cancellable exponential backoff, jitter, and a
frequency cap. A transient bootstrap failure keeps the normal pending UI,
while terminal HTTP outcomes follow their authentication or error flows.
Mounted app frames and shell controls are not removed or replaced because of a
connectivity event. Pending retries are cancelled on unmount, logout, user or
workspace change, and scope revision, and they are never persisted.

M3 implements these shared mechanics in `packages/pwa-cache/` while the public
`features.data_cache` projection remains fail-closed by default. The owned
structured-data database is `maverick-pwa-data-v1`, version 3, with split
metadata/payload stores, transactional migration, durable cleanup markers, and
a RAM fallback. Entry identity contains host-attested user, workspace, owning
app, resource, entity, policy revision, app-owned resource schema revision, and
entry schema version. Every cache hit re-runs the current sanitizer and checks
the exact payload size and TTL timestamps before render. The framework
enforces expiry, least-recent eviction, 64 MiB global and 32 MiB per-app
default budgets, an
app-declared resource budget, and quota headroom from
`navigator.storage.estimate()`; an unavailable estimate skips persistence and
the framework never requests `navigator.storage.persist()`.

Private structured entries require a fresh access lease bounded to 15 minutes.
Base Shell renews that lease only after an authoritative session response,
cancels RAM pending work at principal/scope boundaries, clears the applicable
database scope on logout and `401`/`403`, and routes
`maverick.app.data-changed` to scoped invalidation. Settings may expose only
aggregate byte/entry/quota/backend diagnostics and a confirmed clear action;
it cannot enumerate cached content or clear unrelated origin storage.
Security-sensitive deletion never reports RAM fallback as success: an
incomplete durable clear remains pending and blocks persistent cache access
until the primary store confirms removal. The M3 release does not enable an
app read model or the M4 OPFS file cache.

M4 implements the automatic Storage file-cache mechanics behind the
default-off `features.storage_file_cache` projection. Base Shell owns the
top-level broker and binds it to the freshly authenticated user/workspace and
the fixed `storage` app scope. A mounted Storage frame can request only a
stable file id and source version over a private `MessageChannel`; it never
receives OPFS, IndexedDB, host capability, classification, or scope authority.
The broker independently resolves a server-owned
`maverick.storage-file-cache-descriptor.v1`, rejects a cross-origin or
identity-mismatched media URL, and applies the canonical local-persistence
policy before opening bytes. Until a terminal decision, it revalidates the
exact no-store feature projection for each open. Explicit disable, malformed
success, non-transient HTTP failure, or authentication rejection clears a
positive decision and terminally disables the mounted broker, avoiding
repeated default-off config requests; a later enable requires a new
authenticated broker mount or shell reload. A transient response or transport
failure may reuse only a positive result already confirmed in that
authenticated in-memory broker plus the exact matching server descriptor
already validated in its bounded RAM map. This allows a ready hit during
network loss without persisting the media URL or policy projection; explicit
denial/authentication failure and broker disposal clear the map, while a cold
broker remains fail-closed. Raw Storage bytes default to `unclassified`. An
internal, host-role-attested `file.cache_policy.approve` action can durably
approve only one exact current file id/source version as `workspace_internal`;
`file.cache_policy.revoke`, a version change, an oversized entry, or a missing
approval makes the descriptor ineligible. Public action results redact the
approving actor. Enabling the global flag alone therefore cannot widen the
persistence policy.

The owned file manifest is `maverick-pwa-file-v1`, at IndexedDB version 1 with
record schema 2, and the byte directory is `maverick-pwa-file-cache-v1` in
OPFS. Keys bind user, workspace, app, stable file id, source version, policy
revision, and schema version; random UUID-derived flat OPFS names reveal none
of those values. A writer streams chunks to an unpublished path, records
progress separately, and publishes `ready` only after exact size, strong ETag,
source version, SHA-256, cleanup epoch, identity generation, and budget checks.
Interrupted bytes may resume only in the same browser session with `Range` and
a strong `If-Range`; a changed validator or version discards the partial and
starts a full request.

Candidate hits re-hash the complete physical Blob and make an authoritative
conditional `HEAD` to the media URL. Local Storage hashes the live file and
Drive refreshes the current provider revision before returning its strong ETag;
only exact ETag and size confirmation permits reuse. A transient revalidation
failure may use only the exact positive gate and descriptor already trusted in
the same bounded authenticated broker session; stale or authentication results
evict or reject the candidate, and cold sessions fail closed.

File-cache defaults are 64 MiB per entry, 128 MiB per authenticated Storage
scope, and 256 MiB across the origin, subordinate to the existing quota
headroom check. A shared origin-budget Web Lock reserves the full declared
write size, publication rechecks the budget, and a file-identity generation
ensures that a late older-version writer cannot replace a newer ready version.
Expired write leases, orphan paths, superseded versions, and least-recently
used victims are removed without invoking a Storage server mutation. Missing
OPFS, missing quota information, corruption, and local write failure degrade to
the ordinary network result. Storage routes eligible
image, PDF, text, and markdown preview reads through the broker while video
and audio keep their normal streaming path. Both paths render the same viewer
and loading state, with no cache-residency UI.

Authentication failure, logout, user/workspace transition, and Settings
**Clear cache** use the same durable cleanup barrier across structured entries,
the file manifest, and owned OPFS bytes. File cleanup advances a durable epoch,
cancels affected writers across tabs, waits for their lock/drain
acknowledgement, and leaves the tombstone pending until no old writer can
publish. Diagnostics expose only aggregate structured/file bytes and entry
counts, quota, backend, OPFS availability, and pending cleanup.

All app and widget documents, including Storage, use the isolated app-frame
origin described above. The browser-storage security blocker is therefore
closed at the implementation level. Private file-cache rollout remains blocked
by the default-off flag and by approval/privacy/physical-device evidence, not
by a same-origin shell frame.

The RAM retry coordinator starts at one second, caps its exponential component
at 30 seconds, applies 0.75–1.25 jitter, and enforces a 250 ms minimum interval
for early hints. Only transport/timeouts and `429/502/503/504` are retryable by
the standard classifier. An unsafe request remains one-shot unless it carries
a stable `Idempotency-Key`, exact request fingerprint, and a declared server
deduplication contract; eligible mutations are capped at three attempts and
still cross current server authorization and admission. `401` and `403` remain
the terminal request errors even when their cleanup changes retry scope; they
cannot be masked as cancellation. Base Shell's `pinned_apps.set` mutation is
the M3 end-to-end proof, backed by an atomic bounded App Store deduplication
ledger and duplicate-event suppression.

## Everything Above The Core Is An App

The Maverick product shell should also be modeled as an app.

That means the system may include apps such as:

- `base-shell`
- `chat`
- `agents`
- `skills`
- `app-store`
- `memory`

The `base-shell` app may host the frontend of other apps, but it is still only an app mounted by the core.

The `base-shell` app owns the product shell frontend and should preserve the current Maverick shell interaction model while using core protocols.

That means:

- preserve the user-facing shell design and interaction model where still relevant
- do not copy app-specific API contracts into the core
- do not move shell-specific composition logic into the core
- treat `base-shell` as a sealed server app store artifact under `/apps/base-shell`
- serve its production frontend from its declared build output, currently `frontend/dist`
- let the shell discover mountable apps through the registry instead of static app assumptions

The current `base-shell` implementation is a React/TypeScript app-owned frontend built with Vite.

The core serves only the declared `frontend/dist` artifact and exposes generic shell-facing control-plane APIs.

The first shell-facing API slice is intentionally core-generic, not `base-shell` specific:

- `/api/session`, `/api/auth/login`, and `/api/auth/logout` expose the current user session
- `/api/admin/users` and `/api/admin/workspaces` expose admin-only identity, password reset, role, and workspace assignment management
- `/api/admin/workspace-apps` exposes admin-only workspace app installation and enablement management
- `/api/workspaces` and `/api/workspaces/active` expose workspace list, creation, and active workspace selection
- `/api/apps` exposes enabled app registry records for the active workspace
- `/api/app-store/apps`, `/api/app-store/server-apps`, `/api/app-store/installations`, `/api/app-store/install`, `/api/app-store/install-server`, `/api/app-store/install-local`, and `/api/app-store/uninstall` expose authenticated remote catalog reads, installation-level server app source reads, workspace installation state, remote app installation, registered server source installation, workspace-local app installation, and workspace binding removal
- `/api/status` exposes platform status for the active workspace
- `/api/providers/active` and `/api/runtime/status` expose active runtime provider and runtime sessions
- `/api/settings/provider-setup` exposes the minimal user/workspace/provider payload used by `base-shell` for initial provider setup without loading runtime-session inventory
- `/api/settings/platform` exposes read-only platform/workspace/provider/runtime/recovery metadata for settings UI, excluding cleanup-scope runtime inventory
- `/api/settings/runtime-sessions` and `/api/settings/runtime-sessions/clear` expose the runtime-session inventory in the cleanup scope of the active workspace and the cleanup action used by app-owned settings workflows
- when the active workspace is `default`, only a platform admin may use settings cleanup and the scope expands to every workspace on the server
- when the active workspace is not `default`, cleanup stays limited to that active workspace and is available to platform admins plus admins of that workspace
- cleanup is destructive by design: it terminates provider processes, cancels queued or active turns, removes runtime-session records, turns, events, core-owned state, and the runtime session filesystem root, then invokes app-declared cleanup hooks for app-owned data linked to that runtime session
- `/api/recovery/status` and `/api/recovery/health` expose operator recovery inspection, while `/api/recovery/restart-runtime` is the controlled runtime-restart action surfaced to trusted workspace callers through the core recovery flow

These APIs are platform capabilities that any suitable shell app may consume.

They do not make the core own shell UX, chat project organization, or app-specific settings panels.

When `/api/settings/provider-setup` reports `active_provider: null`, `base-shell` may show an initial provider setup dialog backed by `/api/providers/active`. That dialog is shell UX over generic provider-selection governance; it must not silently select a provider in browser state, load runtime-session inventory, or make Chat own the workspace-wide provider choice.

Admin-facing apps must still stay app-agnostic at the core boundary.

For example, a `settings` app may provide the UI for creating users, resetting a user's password, changing platform roles, and assigning users to workspaces, but the records remain owned by the core identity and workspace governance domains.

Admin app visibility is enforced through generic app contract visibility metadata, not through app-specific branches in the core.

The core filters `/api/apps`, mounted app routes, app-owned widgets, CLI discovery/invocation, MCP discovery/invocation, and compact app discovery according to `visibility.platform_roles`, `visibility.workspace_roles`, and declared capability requirements.
An app that declares `visibility.workspace_roles: ["admin"]` is not listed or mounted for ordinary workspace members, even when the workspace admin is not a platform admin.

The same visibility policy applies to App Store read surfaces.
`/api/app-store/apps` must hide catalog entries whose declared visibility excludes the current user.
`/api/app-store/server-apps` must hide registered server app sources whose resolved contract visibility excludes the current user, unless the user is a platform admin.
`/api/app-store/installations` must hide installed and workspace-local app rows whose resolved app contract excludes the current user, unless the user can manage apps for that workspace.
Workspace-local app projects without a workspace binding are management material and should be visible only to platform admins or workspace admins.

Runtime sessions carry ownership metadata such as `owner_user_id`, `created_by_user_id`, `creator_runtime_session_id`, source app id, and a small platform-minted structured grant list. Destructive runtime operations such as cleanup, interrupt, and restart must authorize against that record: the owner may operate their own session, a workspace admin may operate sessions in that workspace, platform admin authority is a separate explicit override, and any non-owner grant must identify the operation plus a concrete grantee principal. Workspace membership alone is not enough to delete or interrupt another user's runtime session, and client-submitted runtime creation payloads must not mint cleanup, interrupt, or restart grants.

The same ownership rule protects agent-facing transcript reads. Full-access
execution is not transcript authority, and ordinary workspace membership does
not reveal another member's thread titles, counts, or messages. A non-owner
requires workspace/platform admin authority or a platform-minted
`read_transcript` grant; cross-workspace and hidden-session targets fail closed
as not found.

Workspace-wide selections such as provider/model choice and app dependency bindings are governance state. They require workspace admin or platform admin authority; ordinary workspace members may read the resulting status needed to use the workspace, but they must not change the setting for everyone.

Workspace app installation and enablement are separate control-plane states.

An installed workspace app has a binding in the workspace and can be managed by an admin without deleting its data. A disabled installed app remains attached to the workspace, but it must not be listed in `/api/apps`, mounted through `/apps/<mount_app_id>/`, exposed through `/api/apps/<mount_app_id>/backend`, or exposed through app-owned widgets, CLI, MCP, or skills. Only enabled workspace app bindings are visible to normal workspace users and served by the platform host.

For hosted and local deployments, bootstrap credentials and signing/encryption material are installation configuration, not development defaults. The core must require the bootstrap admin credential plus refs or protected key-file paths for signing and encryption material before booting a hosted platform:

- `MAVERICK_ADMIN_USERNAME`
- `MAVERICK_SECRET_KEY_FILE`
- `MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT`
- `MAVERICK_RUNTIME_API_SECRET_REF`
- `MAVERICK_WIDGET_CONTEXT_SECRET_REF`

The installer generates and preserves the secret-store key file and bootstrap secret values outside `.maverick`, defaulting the service env file to `.env.maverick` and the bootstrap secret files to `data/bootstrap-secrets/` for local installs. Systemd units load the env file through `EnvironmentFile=`.
Static known values for admin credentials, runtime tokens, widget context tokens, or secret-store encryption are permitted only in explicit test invocations that set `MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS=1`. `MAVERICK_ENV=development`, `MAVERICK_ENV=dev`, and `MAVERICK_ENV=test` must not by themselves authorize static credentials or signing secrets. `MAVERICK_RUNTIME_API_SECRET`, `MAVERICK_WIDGET_CONTEXT_SECRET`, and `MAVERICK_SECRET_STORE_KEY` remain compatibility/dev fallbacks, not hosted-install defaults.
At hosted startup, `MAVERICK_ADMIN_PASSWORD` and `MAVERICK_ADMIN_PASSWORD_REF` are optional bootstrap inputs. If a bootstrap admin password or password ref is configured, startup creates or repairs the configured admin password credential. If no bootstrap password is configured, startup may create or preserve the configured admin user without a password credential and must not reset an existing admin password. This keeps normal boot independent from plaintext admin credentials.
Admin password recovery is an explicit operator-only core CLI action. It may create or reset the configured admin user's password directly in the durable identity store, revokes existing sessions for that user, and never persists the plaintext recovery password in `.env`, `.maverick`, or bootstrap secret files.

Cookie-authenticated unsafe HTTP methods must carry browser-controlled same-origin proof. If a request with session cookies uses POST, PUT, PATCH, or DELETE and lacks both `Origin` and `Referer`, the platform host must reject it unless a future explicit CSRF token mechanism replaces that proof. A client-controlled custom header is not a CSRF boundary.

The shell may visually frame mounted app frontends, but it must not hardcode optional product apps that are not installed in the current workspace.

This keeps the product shell replaceable and prevents product UI concerns from leaking into the core.

Local hosted bootstrap must rebuild enabled built-in app bindings for every active workspace in the workspace registry, not only for `default`. Workspace selection and `/api/apps` must remain consistent after a host restart because the workspace registry is durable control-plane state while the local app registry is reconstructed at process startup.

Mounted app frontends may request generic shell navigation by posting an explicit app-open message to their parent frame. The shell may honor that request only by opening another app from the workspace app registry; the message is not a filesystem, backend, or privilege boundary.

The completed `base-shell` implementation intentionally carries only shell-owned behavior:

- local browser session state such as active app and sidebar state
- reusable shell UI primitives used by the app itself
- registry-driven app catalog and mounted app iframe surfaces
- login/session UI backed by core identity/session APIs
- workspace selector backed by core workspace APIs
- provider setup gating backed by core provider/runtime APIs
- a registry-gated Settings shortcut that opens the app-owned `settings` frontend instead of rendering settings UI inside the shell

It must not absorb chat project buttons, chat orchestration, retrieval settings, push notifications, or app-specific backend controls into `base-shell`.

Project organization belongs to the chat app because projects are chat-domain state, not shell or core platform state.

If the product shell needs to show app-specific navigation in its sidebar, it must do so by mounting app-owned widgets through the generic widget registry. The default `base-shell` sidebar owns the fixed frame and reserves standard widget slots, but it does not own the data, labels, or actions rendered inside those slots.

If the product shell needs to show app shortcuts in its sidebar, it must do so by mounting an App Store-owned widget through the same generic widget registry.

`base-shell` may keep a fixed `Apps` entry that opens the App Store, but it must not own or hardcode the shortcut list. Pinned app shortcut state belongs to `app-store` workspace data and is mutated through the App Store app's own backend surface.

The intended sidebar shape is:

- `base-shell` owns the fixed sidebar frame: current app icon, workspace selector, mobile app rail, responsive layout, overlay behavior, scroll containment, fades, and shell mode controls
- on desktop, the app rail is always a layout-reserved side rail; overlay sidebar mode may overlay only the expanded sidebar details panel beyond that rail, while fixed mode reserves both the rail and details panel
- on mobile, `base-shell` owns a shell header above mounted app iframes; the mobile workspace reserves the header height so app content starts below it, while the header opens the sidebar from the active app icon, opens a new Chat launch from the centered logo, and exposes a right-side primary action button
- on mobile shell entry or refresh, the sidebar starts closed even when the local desktop sidebar session was open or fixed
- mobile sidebar opening must not depend on a left-edge swipe over mounted app iframes; app content keeps normal horizontal touch behavior unless the sidebar is already open
- the mobile header primary action is a generic shell-to-widget invocation of the active app's `shell.sidebar.footer` widget; the footer widget owns whether the action is available, whether the sidebar surface should be made visible before invocation, and what app behavior it triggers
- `shell.sidebar.primary` is the app-owned central sidebar body for the active app only
- `shell.sidebar.footer` is an app-owned compact footer action area for the active app only, positioned inside the fixed shell footer above shell mode controls
- `base-shell` chooses sidebar widgets by matching `owner_app_id` to the active app id; if the active app has no matching widget for a sidebar slot, that slot stays empty rather than falling back to another app's widget
- `base-shell` does not render generic content skeletons for app-owned sidebar slots; each app-owned sidebar widget renders its own loading state so reloads and app switches have a single loading owner
- `base-shell` must keep shell-owned app rail and active-app chrome free of app runtime busy indicators; runtime busyness belongs inside app-owned widgets such as Chat's sidebar and floating surfaces
- `app-store` may own an `app-shortcuts` widget compatible with a shell shortcut content kind when a shell variant exposes shortcut content
- `chat` owns a `chat-sidebar` widget for `shell.sidebar.primary` and a separate `chat-sidebar-footer` widget for `shell.sidebar.footer`; "new chat" remains Chat-owned even though the footer container is shell-owned
- chat sidebar widgets, when mounted by a shell variant, load and mutate thread records through the core runtime thread surface and use chat-owned backend surfaces only for chat projects and view state
- `base-shell` keeps the iframe-mounted widget alive while the sidebar is hidden, so opening and closing the menu does not reload app-owned widget state
- `base-shell` may react to a generic browser message asking it to open an app with scalar navigation params, but it must not import chat code or call chat-private internals
- `base-shell` keeps mounted app iframe documents alive after first open and sends app navigation through a generic `postMessage` protocol instead of rebuilding iframe URLs for every internal app route
- `base-shell` should keep the previously visible app frame on screen while a newly requested app frame cold-mounts hidden, then reveal the target frame only after the target acknowledges first render readiness or reaches a bounded post-load fallback
- `base-shell` listens to the core app-event WebSocket and may remount only the affected app iframe after a successful official frontend rebuild event
- `chat` owns project settings panels and "new chat" UI behavior; thread rename, move, delete, and delete-all operations call core runtime thread APIs

Mounted app navigation is intentionally message-driven.

The shell may activate an app frame and send:

```json
{
  "type": "maverick.app.navigate",
  "app_id": "chat",
  "params": {
    "thread_id": "thread_123"
  }
}
```

The shell must not append chat-specific query strings such as `thread_id` to the mounted iframe URL after the app is loaded.

This keeps iframe identity stable, prevents full app reloads during sidebar navigation, and preserves app-owned in-memory state.

The receiving app owns the meaning of the scalar params.

The core and shell only provide the generic delivery mechanism.

If an app asks the shell to open a workspace-local app from a workspace that is not currently active, the open request must include the target `workspace_id`.

The shell may switch the active workspace through the generic workspace API, reload the app registry, and then mount the requested app.

This does not make workspace-local apps cross-workspace capabilities: the app still mounts only after the shell enters the workspace that owns the app binding.

One-shot navigation commands must be idempotent at the receiving app boundary.

For example, `chat` may accept `{ "new_chat": true }` from a shell widget, but that request must include a unique app-owned request id such as `new_chat_request_id`, and the chat app must consume that id only once. This prevents repeated iframe ready/navigation handshakes from creating duplicate empty threads.
The shell must deliver one-shot command params through the app navigation message and must not persist them in the user-facing `/app/<app_id>` URL.
Current transient command params include `new_chat`, `new_chat_request_id`, `new_agent`, `new_agent_request_id`, `new_skill`, `new_skill_request_id`, `new_node`, `new_node_request_id`, `preview_context`, and `preview_context_request_id`.

Creating a new empty chat thread must not preallocate or start a runtime session. A runtime session is created only when the first user message or an explicit runtime-session handoff requires execution. For a draft chat's first user message, Chat must create the runtime session and queue the first turn in one runtime request before doing route/catalog work that is not required to persist the message; default title generation is follow-on thread metadata from the queued message and must not be a prerequisite for starting the turn. Core may mark a new thread title as pending and resolve it asynchronously through a bounded AI micro-task, provided the thread remains visible and usable while the title is pending and a deterministic fallback clears the pending state if model generation fails.

Runtime sessions are user-visible by default for legacy compatibility: missing `session_kind` is interpreted as `chat_root`, and missing `thread_visibility` is interpreted as `user`. Explicit `inter_agent_participant` sessions are the exception: they must be hidden, omitted visibility on a participant is normalized to `hidden`, and explicit `thread_visibility=user` is invalid for that kind. Invalid persisted visibility values fail closed and must not make a runtime session appear in user-facing thread catalogs. Sessions with `thread_visibility=hidden`, such as `inter_agent_participant` child sessions, may have turns, runtime events, provider state, and process records, but must not create a `RuntimeThreadRecord`, appear in Chat catalogs, or be opened through runtime thread APIs. Direct attempts to create or open a runtime thread for a hidden session must fail with `runtime_session_hidden`. Direct raw runtime HTTP routes and runtime session WebSocket streams must also apply server-side visibility: hidden sessions are excluded from `GET /api/runtime/sessions`, rejected from direct session, event, turn, submit-turn, cleanup, and turn-interrupt HTTP access, and rejected by `WS /ws/runtime/sessions/<session_id>`. App-owned runtime launch, interrupt, and cleanup request envelopes must apply the same hidden-session rejection and may not operate hidden inter-agent participants outside the inter-agent service.

When a provider such as the built-in `agents` app is installed and enabled in the active workspace and satisfies both `agent.catalog` and `agent.prompt-materializer`, `chat` may use that provider's backend surface to initialize a draft chat with a selected agent prompt and skill metadata. This is an app-to-app use of official app backend surfaces, not a core dependency: the core must not read Agents data, parse role files, or special-case the Chat/Agents relationship. Chat may expose the selection in its composer before the first user turn; once a runtime session exists, that session keeps its original app-provided prompt and agent metadata.

For example, the Agents app may create a generic core runtime session and ask the shell to open Chat with:

```json
{
  "type": "maverick.app.open-app",
  "app_id": "chat",
  "params": {
    "runtime_session_id": "runtime_session_123",
    "agent_label": "Backend Systems Engineer",
    "agent_type_id": "backend-systems-engineer",
    "thread_title": "Backend Systems Engineer"
  }
}
```

The shell should only activate Chat and deliver the scalar params.

Chat asks the core runtime thread API to create or reuse the thread record for that runtime session because thread state is core runtime data.

If that creates or changes thread data that is also represented by an embedded widget, the widget receives the new thread catalog through `WS /ws/runtime/threads`. The app may emit an app-owned UI message only to mirror active selection:

```json
{
  "type": "maverick.chat.active-thread-changed",
  "owner_app_id": "chat",
  "active_thread_id": "<thread_id>"
}
```

The shell may forward that selection message to mounted widgets owned by the same app.

The shell must not inspect, mutate, or reconstruct the app data.

The receiving widget owns the refresh behavior.

Mounted apps should also emit:

```json
{
  "type": "maverick.app.ready",
  "app_id": "chat"
}
```

The shell should treat this as a lifecycle acknowledgement that the app has completed its first useful render, which may still be an app-owned loading skeleton. The shell should then reveal a cold-mounted target frame and resend the latest pending navigation params for that mounted app.

This keeps navigation reliable after login/logout cycles and cold iframe mounts without switching back to query-string driven iframe reloads.

### Current Product Assumptions To Remove

The current code keeps the core/app boundary clean at the import level: `core/` does not import app frontend code, and `base-shell` does not import `chat`.

There is still a product assumption that should be removed before calling the core and apps fully standalone:

- `base-shell` currently prefers/pins `chat` as the initial app in local browser state instead of deriving the first-open app from workspace preference or registry metadata

Built-in app bootstrap is contract-driven and scans installation-level app roots that contain `app_contract.json`.
Future production packaging may still narrow the default installed set through installation configuration or app-store metadata, but the core bootstrap no longer names individual app ids for discovery.

The root `/` platform route is configured through the hosted platform state.
The local hosted default is `base-shell`, and operators may override it with `MAVERICK_ROOT_SHELL_APP_ID`.
That default is a bootstrap configuration value, not a core dependency on the shell app's internals.

These assumptions are not direct code-contamination problems because they do not import app internals into core.

They are product defaults encoded in code, and they should become configuration or registry-driven policy.

The rule is:

- the core is the platform host
- every product extension above the core is an app

## Human And Agent Interfaces

Apps in Maverick are not only visual applications.

An app may need to serve:

- a human user through `frontend/`
- app-specific backend logic through `backend/`
- agents through `mcp/`
- operators or agents through `cli/`
- agent guidance through `skills/`

This is the intended target model.

The real value of an app is not only that it renders a screen.

The core distinguishes frontend asset serving from frontend launchability. `entrypoints.frontend` means the platform can mount and serve an app's frontend artifact, while `presentation.frontend_role` says whether that frontend is a user-openable workspace app (`workspace`) or a supporting platform/plugin surface (`supporting`). Registry and App Store payloads expose the derived `frontend_launchable` flag so shells and shortcut widgets do not hardcode app ids when deciding what can be opened or pinned.

The real value is that it extends the platform for both:

- humans
- agents

under one mounted app contract.

## Deployment Surfaces

For the first real hosted deployment, the intended shape is:

- `nginx` as the public ingress
- one main core service behind the deployment hostname
- one independent rescue service that does not depend on the main backend staying alive

The default assumption should not be one `systemd` service per app.

At least in the first implementation wave, apps should be mounted by the core rather than deployed as independent public services by default.

This keeps the architecture aligned with the platform-host model.

The rescue path is different.

It should remain independently deployable so the user can still reach recovery tooling even if the main platform service is unhealthy.

For the first hosted wave, this means:

- one main core host mounted at the deployment hostname
- one separate rescue host
- one backend watchdog timer that probes the main core host from outside the main backend process
- a minimal app set mounted by the core:
  - `base-shell`
  - `chat`
  - `agents`
  - `skills`
  - `app-store`

The main core host should run through the ASGI platform host so HTTP and WebSocket traffic share the same `PlatformState` and persistence adapters.

The main `/health` endpoint must be served directly by the ASGI host without entering mounted app dispatch or the synchronous WSGI worker pool, so app, MCP, CLI, or runtime entrypoint saturation cannot hide basic backend liveness from the external watchdog.

Mounted app backend routes under `/api/apps/<mount_app_id>/backend` must run through a dedicated ASGI executor instead of the generic WSGI dispatch pool, so slow app-owned subprocess work cannot starve core HTTP surfaces. `MAVERICK_APP_BACKEND_WORKERS` may tune that executor locally; the default should stay small enough to bound subprocess fan-out.

The ASGI host must implement `lifespan` shutdown so active mounted app backend subprocess trees are terminated cooperatively during service restarts instead of relying on `systemd` timeout kills.

The authorized non-root backend restart fallback may signal the systemd-managed main process when `systemctl restart` requires interactive authentication. Its deferred self-restart helper must bound the graceful-shutdown wait and escalate only after verifying that the target PID still belongs to the same process incarnation. This prevents a stalled ASGI request from leaving systemd reporting an active service whose listening socket has already closed, without risking a signal against a reused PID.

The WSGI host may remain useful for isolated local smoke checks, but it is not the production runtime host once WebSocket is part of the agent communication surface.

`nginx` must forward `/ws/` and WebSocket-capable API routes such as `/api/apps/events/ws` with `Upgrade` and `Connection: upgrade` headers to the main core host.

The backend watchdog is deployment infrastructure, not app runtime behavior.

It should run as a small `systemd` timer that probes the main backend health endpoint once per minute and persists downtime state under installation-local recovery state. If the backend is continuously unhealthy for at least 300 seconds, it may launch one autonomous rescue agent from the independent rescue path with full host access, using the authoritative provider configured for platform recovery. The rescue prompt must require a forward minimal fix against the current tree, must forbid git rollback operations such as `git reset`, `git checkout`, or `git restore`, and must preserve unrelated user changes.

If no provider is configured or the configured provider is unavailable, the watchdog must not assume Codex. It should persist and expose a clear blocked state, such as `blocked: no_provider_configured`, without preventing the core from being installed or booted.

The watchdog resolves the recovery provider from durable installation-local provider selection state, not from an independent raw shell command. Provider adapter configuration may still supply provider-specific command details for the selected provider, but that command is not a separate source of recovery authority when no provider is configured.

The rescue agent should diagnose the current code and deployment state, apply the smallest fix that restores the backend, run targeted verification, restart `maverick-core.service` when systemd is available, and verify the health endpoint. It must not manually recreate product runtime agents. Runtime session spin-back remains the backend startup recovery responsibility described in the runtime recovery section.

## Target Core Tree

The target core tree should look like this:

```text
/maverick/
  core/
    api/
    main.py
    identity/
    workspaces/
    apps/
    runtime/
    inter_agent/
    providers/
    execution_policy/
    secrets/
    recovery/
    observability/
    mcp/
    cli/
    skills/
```

Notes:

- `api/` is the application bootstrap surface for backend or HTTP process wiring
- `mcp/` and `cli/` are executable capability surfaces of the same core
- `skills/` is instructional only
- every other top-level directory under `core/` should represent a real Maverick core domain

## Core Versus Agents App

The core owns the runtime and provider layers.

One supported runtime backend today is:

- `Codex`

The core should not encode "Codex" as the product-wide definition of an agent type.

The architectural distinction is:

- runtime abstraction = core
- backend provider implementation = core
- workspace agent definition = app

The app `agents` owns:

- workspace-specific agent definitions
- prompt compositions
- role-specific system prompts
- shared prompt templates
- catalog of agents visible in a workspace

So:

- runtime execution and provider selection = core
- workspace agent definitions = app

## Core Versus Memory

Memory is entirely an app concern.

The core should not own:

- memory notes
- memory links
- memory indexing semantics
- memory retrieval semantics

If a memory app exists, it owns those concepts inside the workspace.

## Architectural Boundary

The core should interact with workspaces and apps through stable contracts.

That means:

- the core hosts and orchestrates
- the app owns its data and domain model
- the workspace contains app-owned persisted state

The core must not depend on:

- app-specific schema internals
- app-specific embedded database layout
- app-specific indexing internals

This boundary must remain true across:

- `mcp/`
- `cli/`

and must not be weakened by instructional assets under `skills/`.

## Filesystem Position

The core lives at installation level under:

```text
/maverick/core/
```

It is outside:

- workspace data
- workspace app data
- workspace storage

The core must never become a general-purpose dumping ground for workspace-derived content.

## Core Structure Direction

The target structure of the core should separate the following concerns.

The structure should optimize for:

- small files
- narrow responsibilities
- obvious folder ownership
- naming that reads well in long file trees
- minimal need to open a file to guess what it does

The core should prefer many small explicit modules over a few generic buckets.

### `identity/`

Owns:

- users
- auth
- sessions
- membership logic

### `workspaces/`

Owns:

- workspace registry
- governance
- quotas
- workspace policy

### `apps/`

Owns:

- app hosting
- install state
- lifecycle orchestration
- compatibility checks

This does not mean app business logic lives here.

It means the platform side of app management lives here.

### `runtime/`

Owns:

- runtime session lifecycle
- turn management
- runtime event flow
- process lifecycle
- execution orchestration
- runtime state transitions

This package should be provider-agnostic.

The HTTP runtime API is a host surface over this domain, not the domain itself.

The ASGI platform host is the canonical interactive host because it serves both:

- REST-style HTTP APIs used by apps and operators
- WebSocket runtime streams used by apps that need realtime agent communication

Current first-use endpoints include:

- `POST /api/runtime/sessions`
- `GET /api/runtime/sessions`
- `GET /api/runtime/sessions/<session_id>`
- `GET /api/runtime/sessions/<session_id>/events`
- `GET /api/runtime/sessions/<session_id>/turns`
- `POST /api/runtime/sessions/<session_id>/turns`
- `POST /api/runtime/sessions/<session_id>/cleanup`
- `GET /api/runtime/turns/<turn_id>`
- `POST /api/runtime/turns/<turn_id>/interrupt`
- `POST /api/runtime/threads/<thread_id>/read`
- `WS /ws/runtime/sessions/<session_id>`
- `WS /ws/runtime/threads`

Turn submission accepts `delivery_policy=queue_next` by default. Interactive Chat surfaces use `steer_or_queue`: the core serializes the decision per runtime session, attempts same-turn admission only for a capable provider and an active, provider-accepted turn, and never steers past an already queued message; every explicit rejection or turn race falls back to a normal queued runtime turn. A successful admission returns `delivery=steered` and persists `runtime.message.steered` on the existing turn. A write or acknowledgement timeout returns `runtime_message_delivery_uncertain` and must not be converted into an automatic queued retry because the provider may already have accepted the message.

Inter-agent F2 runtime operations are exposed through the core-owned inter-agent
surface, not through raw hidden runtime routes:

- `GET /api/inter-agent/generalist-context?root_runtime_session_id=<id>`
- `POST /api/inter-agent/orchestrations`
- `POST /api/inter-agent/runs`
- `GET /api/inter-agent/runs`
- `GET /api/inter-agent/runs/<run_id>`
- `GET /api/inter-agent/runs/<run_id>/events`
- `POST /api/inter-agent/runs/<run_id>/participants`
- `POST /api/inter-agent/runs/<run_id>/messages`
- `POST /api/inter-agent/runs/<run_id>/directives`
- `POST /api/inter-agent/runs/<run_id>/execute`
- `GET|POST /api/inter-agent/runs/<run_id>/wait`
- `POST /api/inter-agent/runs/<run_id>/interrupt`
- `POST /api/inter-agent/runs/<run_id>/resume`
- `POST /api/inter-agent/runs/<run_id>/close`

The matching core CLI commands are `inter-agent.runs.create`,
`inter-agent.participants.spawn`, `inter-agent.messages.send`,
`inter-agent.runs.execute`, `inter-agent.runs.wait`, `inter-agent.runs.interrupt`,
`inter-agent.runs.resume`, and `inter-agent.runs.close`. The matching MCP tools
are `inter_agent_run_create`, `inter_agent_participant_spawn`,
`inter_agent_message_send`, `inter_agent_execute`, `inter_agent_wait`,
`inter_agent_interrupt`, `inter_agent_resume`, and `inter_agent_close`.

Static `manager_tools`, `sequential`, `concurrent`, and `group_chat` runtime
participants persist a task-local `invoked_skill_ids` receipt separately from
their assigned `skill_ids` allowlist. The native executor forwards that exact
receipt on the participant turn. Direct HTTP, CLI, and MCP message surfaces
accept the same structured field and never infer authority from `$skill-id`
text. Dynamic orchestration catalog prompts expose each selectable agent's
skill activation mode and bounded allowlist metadata, including the default
root worker; an open explicit allowlist is populated best-effort from the
enabled selected workspace catalog. Failed-task ledger entries include a
bounded error cause so the orchestrator can schedule a corrected task instead
of guessing why dispatch failed.

For orchestrated runs, all three resume surfaces dispatch through the hosted
scheduler handoff: wait for the previous in-process owner, reconcile persisted
state, then start the replacement worker. Runtime-authenticated CLI and MCP
calls receive that hosted coordinator from the backend. A standalone sidecar
without a hosted scheduler owner must reject orchestrated resume rather than
leave the run `running` without execution.

Inter-agent mutation surfaces share the same run authority rule: the local
operator, the run creator, a platform admin, or a workspace admin may mutate a
run. Sandbox CLI and MCP callers do not gain mutation authority from
`WORKSPACE_SAFE` discovery alone.

Runtime session creation must include an explicit `agent_id`.
The core must not default missing runtime ownership metadata to a product app such as Chat.

Turn submission is implemented through a dedicated runtime service so future CLI, MCP, WebSocket, or automation surfaces can reuse the same orchestration without embedding execution logic in HTTP route handlers.

The runtime WebSocket endpoints are the official realtime transports for mounted apps and other interactive clients.

`WS /ws/runtime/sessions/<session_id>` sends a `runtime.snapshot` frame containing session metadata, a bounded recent tail of persisted events, and the runtime turn records needed to project that bounded page even when it starts mid-turn, then live `runtime.event` frames from the runtime event bus. Clients may request older persisted pages over the same connection with `runtime.history.before` and receive `runtime.history.page`; history pages carry the same bounded event page plus the relevant turn records. Initial chat load must remain bounded and independent of total transcript length. `WS /ws/runtime/threads` sends a `runtime.thread.snapshot` frame containing only user-visible workspace runtime threads, ordered by the most recent accepted user message for each thread, then live `runtime.thread.changed` frames from the runtime thread event bus. Thread frames include core-derived response completion metadata such as `last_completed_response_at`, `last_completed_turn_id`, and the viewer-specific `has_unread_completed_response` boolean. Per-user read receipt storage remains internal to the core runtime thread record and must not be exposed as a raw user-id map in app payloads.

Filesystem-backed snapshot projection must not run on the ASGI event-loop thread. The transport subscribes before projection and builds blocking catalog snapshots in a worker. All ASGI WebSocket transports keep their pending client-receive, event-subscription, and shutdown tasks alive across heartbeat or polling timeouts, then cancel and drain them only during teardown. A slow catalog read, idle heartbeat, or inter-agent poll must not stall unrelated HTTP/widget traffic or cancel the underlying ASGI receive channel.

The HTTP event and thread endpoints remain command, diagnostics, and operator surfaces. Product chat rendering must not bootstrap transcripts or thread lists by replaying runtime data over HTTP.

Bulk runtime-session diagnostics must project provider governance from one
request-scoped registry and read-through provider snapshot. Repeated sessions
may reuse parsed definition, certificate, evidence, binding, and adapter
artifact inputs only within that request; each session still receives its own
live authority projection, and no mutable governance result may survive into a
later request.

Apps that want realtime agent updates should connect to the WebSocket surface directly.

They should not implement app-specific WebSocket routes for core runtime events.

### Runtime token usage and context metering

`core.usage` owns provider-neutral token metering. Provider adapters may report incremental request usage or cumulative thread snapshots, but the usage service must normalize those reports into idempotent `UsageSampleRecord` deltas before aggregation. When a cumulative provider exposes both a lifetime total and the latest-request breakdown, the first observation uses the latest request as the local increment and retains the lifetime counters only as the baseline for later deltas. A pre-existing lifetime total must never be presented as newly observed consumption. Token categories remain additive: uncached input, cached input, cache-write input, non-reasoning output, and reasoning output are stored separately. Every sample carries provider/model attribution plus explicit token and context accuracy (`exact`, `estimated`, or `unavailable`); clients must not present an estimate as an exact provider report.

Active context and cumulative consumption are different values. Active context is the latest root-session provider snapshot divided by that model's context window and may decrease after provider compaction. Chat consumption is the monotonic sum of normalized samples for the root session and every descendant runtime session reached through `creator_runtime_session_id`, with direct and delegated subtotals. Provider subscription limits are a third, separate concept: they describe account windows and must not be inferred from chat tokens or context percentage.

Canonical samples, hourly/daily provider-model buckets, and redaction-safe provider-quota observations are core-owned control-plane records. The JSON adapter stores them below `data/control-plane/json/usage/`; Mongo uses dedicated indexed collections. Runtime cleanup removes detailed samples for deleted sessions. Historical coverage starts when metering is deployed; neither the API nor the UI may imply that older unobserved turns were reconstructed.

The root runtime WebSocket snapshot includes an authoritative `usage` projection. Every physical session in the root chat's continuation lineage counts as direct usage, so a compatible authority fork neither freezes the active-context meter nor reclassifies subsequent work as delegated. Newly inserted samples publish a persisted `runtime.usage.updated` event to the current root-lineage session, including when the observed work ran in a hidden delegated child, so Chat updates without polling. `GET /api/runtime/sessions/<session_id>/usage` exposes the same session-authorized projection for diagnostics. `GET /api/usage/timeseries?resolution=hour|day&periods=<n>` is platform-admin-only, derives workspace scope from the authenticated session, supports provider/model filtering, fills empty UTC buckets, and returns only redaction-safe aggregate data plus provider/model facets for the requested period. Chat renders the current-context percentage and numeric non-cached tokens in the composer and keeps cached input and the complete processed breakdown behind a dialog. Settings defaults workspace charts to non-cached usage, exposes metric/provider/model/range filters, and keeps cached and processed totals visible while provider subscription gauges remain separate.

### Runtime model decomposition

The runtime domain should separate at least these concepts:

- runtime session
- runtime turn
- runtime event
- runtime process
- runtime state

Those are related, but they are not the same thing.

The first implementation should keep those boundaries explicit instead of collapsing them into one generic session manager.

#### Runtime session

A runtime session is the lifecycle container for one running agent runtime.
Creation is logically atomic across the session aggregate, optional bound
provider state, and initial runtime-state snapshot through a persisted
publication barrier: the aggregate is first `unprepared`, initialization writes
are idempotent, and only a final compare-and-set marks it `prepared`. Exact
retries repair an interrupted preparation; conflicting retries are rejected.
An unprepared session cannot transition to `running` or cross the
provider-start handoff. Persisted records from before this barrier are treated
as prepared because the former creation path exposed them only after all
initialization writes returned successfully.

It should carry:

- authoritative runtime ownership such as `workspace_id` and agent or instance identity
- effective execution mode
- lifecycle timestamps
- current session status

The first local implementation should use explicit canonical statuses such as:

- `created`
- `running`
- `stopping`
- `stopped`
- `failed`

#### Runtime turn

A runtime turn is one unit of execution inside a runtime session.

It is not the same thing as chat-thread persistence.

The runtime turn model should support at least:

- queued
- active
- completed
- failed
- cancelled
- timed out

The first local implementation may represent `timed out` as an explicit terminal turn status rather than as an inferred transport-side error.

#### Runtime event

A runtime event is a structured state or progress signal emitted by the runtime domain.

Examples:

- turn started
- tool invocation started
- tool invocation completed
- runtime stalled
- process exited

Runtime events should be modeled independently from WebSocket framing or any other transport protocol.

The transport may carry runtime events, but it must not define the domain model.

When a runtime turn is submitted with a client-generated message id, the core should carry that id through the queued-turn event payload.

That id is not a chat-specific concept.

It is a generic correlation value that lets mounted apps reconcile optimistic UI state with authoritative runtime events without duplicating user messages.

The queued-turn event may also carry runtime input attachment metadata.

Attachment metadata is not file storage.

The core file upload surface persists file bytes under workspace storage and returns stable metadata. Uploads and JSON HTTP/ASGI request bodies must be bounded before decoding or dispatching so malformed, non-object, or oversized bodies return stable 4xx errors instead of becoming unbounded memory pressure or generic 500s. WSGI and ASGI hosts must resolve the body-size limit through the same configuration path. Runtime turns should carry references such as `file_id`, `relative_path`, content type, size, and checksum, not inline file bytes.

Before dispatching a turn to a text-oriented provider backend, the runtime should materialize uploaded attachment references into the provider input as workspace-relative links and local workspace paths. The queued runtime event should still preserve the original user text and structured attachment metadata for transcript rendering.

Provider lifecycle prompts such as waiting for stdin, turn start, turn completion, turn diff update, turn plan update, and item start or completion are internal runtime noise.

The provider normalization layer should drop those lines before they become persisted runtime events or frontend transport frames.
Chat-facing runtime views may still defensively ignore such labels, but the core runtime must not publish them as user-visible progress.

The first HTTP implementation supports async turn submission through an explicit request flag.

In async mode:

- the route queues the turn
- the route returns immediately with `202 Accepted`
- the provider execution runs in a background worker
- ordered runtime events record start, step updates, tool calls, output deltas, final output, completion, failure, or cancellation

Interactive runtime turns must not have a fixed wall-clock timeout.

An agent may work for minutes or hours inside one turn. The core may keep short protocol handshakes bounded, and users may explicitly stop a turn, but the runtime must not interrupt active provider work solely because a static turn-duration timer expired.

If the provider transport itself terminates while a turn is active, that is a terminal transport failure rather than a long-running healthy turn. For Codex app-server, a closed stdout reader or reader-loop exception must fail and unblock the active turn instead of leaving the worker waiting forever for `turn/completed`.

Provider adapters may emit provider-specific raw output, but the runtime domain must normalize it before persistence.

For Codex, the local provider runs a persistent `codex app-server --listen stdio://` process and maps app-server JSON events into generic runtime events such as:

- `runtime.step.updated`
- `runtime.tool_call.started`
- `runtime.tool_call.updated`
- `runtime.tool_call.completed`
- `runtime.tool_call.failed`
- `runtime.output.delta`
- `runtime.output.structured`

The Codex adapter must not silently drop app-server notifications just because their method name is not yet known by Maverick.

Known methods should be mapped intentionally. Codex app-server item types such as `commandExecution`, `fileChange`, and `webSearch` must be normalized as first-class generic tool calls with stable `tool_kind`, `tool_call_id`, status, summary, and structured detail fields such as command output, file changes, web-search query, and web-search results.

If an app-owned CLI, MCP, or backend surface returns a generic `chat_render` object, the runtime/provider bridge should normalize it into structured runtime output instead of treating the whole JSON response as assistant prose. The same normalization rule applies when an agent-message completion intentionally returns a JSON envelope with `structured_content` or `chat_render`. The normalized event shape is provider-agnostic: `runtime.output.structured` carries `structured_content` with a stable `kind` and `payload`. Chat and other host apps must resolve that kind through the widget registry; they must not hardcode a specific app such as Dynamic Views.

Provider output that belongs to a tool item must remain tool output. For example, Codex `item.fileChange.outputDelta` notifications are file-change tool updates and must not be emitted as assistant `runtime.output.delta` text.

Provider output deltas that are only low-level command stream fragments are not chat-facing runtime history. For Codex, `item.commandExecution.outputDelta` records represent partial stdout/stderr fragments for an already tracked command execution item, and `item.commandExecution.terminalInteraction` records represent terminal protocol interaction rather than a separate user-visible tool call. They should be filtered before runtime-event persistence and transport; the chat-facing history should retain the command lifecycle and final aggregate result instead of storing every intermediate fragment or terminal handshake.

Codex agent-message output may arrive both as streamed `item/agentMessage/delta` fragments and as a later completed item snapshot. The adapter must emit the text once per provider item: completion snapshots should fill gaps when no delta was streamed, but must not be re-emitted as duplicate transcript output for an item already streamed.

Unknown methods should still become generic runtime events with `provider_event_type` and compact raw payload preserved. If the method or payload looks like a tool, search, browser, fetch, command, or execution operation, it should be emitted as a generic `runtime.tool_call.*` event so the chat UI can show that a tool was used while the exact provider schema is still being learned.

Tool-like provider notifications without an explicit lifecycle state are point-in-time observations. They should be normalized as completed tool calls instead of active updates, otherwise generic notifications such as provider progress activity can leave stale spinners in transcript views.

Provider lifecycle and telemetry notifications that do not represent user-visible work should be filtered from chat-facing runtime steps. Account rate-limit refreshes and generic thread status changes are discarded; token-usage notifications are consumed by `core.usage`, persisted only as normalized redaction-safe samples and root usage projections, and never shown as raw provider telemetry in the transcript.

The Codex adapter must not use stateless `codex exec` for interactive chat or agent sessions.

When a Codex turn is interrupted or a session becomes idle, cleanup must terminate the live app-server process, not only forget its in-memory handle. The primary process registry should be used first, and cleanup may fall back to the runtime session environment marker for Codex app-server processes that survived after the app-server client registry went out of sync.

Before launching the Codex process, the adapter must prepare a runtime-scoped `CODEX_HOME`.

This home is operational provider state for one logical Maverick provider
conversation. An ordinary session owns it below that session's runtime root. A
compatible continuation child reuses the lineage-root session's `CODEX_HOME`:
Codex persists the provider thread in its local database together with an
absolute rollout path, so transferring only the thread id or copying the
database to a different root cannot resume the conversation safely. Core must
serialize continuation admission with ordinary message admission, reject a
fork while either side owns a queued, active, or waiting turn, fence
provider-state updates, and prove that the predecessor app-server process is
closed before provider-state ownership moves or the child becomes executable.
A missing, symlinked, or non-canonical lineage home fails as
`provider_thread_missing`; the adapter must never replace it with a new provider
thread. The operating-system sandbox receives that same canonical lineage home
as `HOME` and `CODEX_HOME`, so Codex cannot resolve its database or rollout
through a session-local home that differs from the ownership root.

The home must live below the continuation lineage's session roots, not in the
workspace data plane and not inside the source repository. The initial session
runtime root is
`workspaces/<workspace_id>/runtime/sessions/<runtime_session_id>/`, so
independent concurrent agents in the same workspace receive separate provider
homes, temporary directories, copied runtime skills, and transient provider
binaries. Physical runtime records other than the explicitly inherited Codex
home remain partitioned by the session that produced them, and lineage-aware
cleanup removes the complete conversation lineage together.
Runtime history and operational records for that agent session must also be partitioned there. The core stores per-session runtime records under the session root, including:

- `session.json` for the runtime session lifecycle record
- `events.json` for the bounded hot tail used by fast runtime replay
- `events-history/` for append-only chunked persisted runtime event pages and chat transcript projection
- `turns.json` for turn lifecycle records
- `processes.json` for local process metadata
- `state.json` for the mutable runtime state snapshot

Workspace-scoped runtime thread records are persisted under `workspaces/<workspace_id>/runtime/threads.json`. Runtime thread records may include the latest successfully completed response timestamp, the completed turn id, and per-user read receipt timestamps so mounted chat surfaces can distinguish read chats from chats whose latest generated response has finished.

The core must not append every agent's session metadata, thread metadata, history, or operational records into installation-level shared JSON files because replay, cleanup, and restart recovery would degrade as total server history grows and would mix workspace-owned runtime state with platform control-plane state. Installation-level runtime persistence is reserved for platform security records such as runtime API token lifecycle state.

Runtime API tokens issued into provider launch environments must have store-backed lifecycle records keyed by token id. Runtime CLI and SDK APIs must reject tokens that are unregistered, expired, revoked, or mismatched against the session workspace and effective mode. This lets the platform revoke one runtime token without trusting bearer-token signature validity alone for the rest of the token TTL.

The source of Codex identity/configuration is configurable and path-agnostic:

1. `MAVERICK_CODEX_HOME`
2. `CODEX_HOME`
3. the current operating-system user's default Codex home

The adapter may copy required files such as auth, version, installation identity, sanitized config, and rules.

The sanitized runtime config must remove inherited MCP server and plugin sections from the operator Codex home. Maverick runtime sessions should not automatically expose user-global Codex connector apps such as GitHub, Gmail, Photoshop, AllTrails, or Notion unless Maverick explicitly materializes an allowed tool surface for that runtime.

The Codex adapter owns Maverick's managed Codex model selection for runtime agents. It should discover the visible Codex model catalog through the configured Codex binary, expose the viable model and reasoning-effort options through generic provider settings, and write the workspace-selected `model` plus the session-selected `model_reasoning_effort` into each runtime-scoped Codex config instead of inheriting those values from the operator home. Reasoning is not workspace-default authority. The fallback model is `gpt-5.6-sol`. New sessions default to the deepest supported single-agent reasoning effort: `max` when the model exposes it, otherwise the next deepest advertised effort. Codex `ultra` is a multi-agent execution mode rather than a reasoning effort and must not appear in the reasoning selector. Persisted model catalogs are normalized to this contract without requiring code changes when Codex adds or removes visible models.

Persisted execution-binding digest compatibility remains fail closed. A newly materialized default may be excluded from legacy digest validation only as part of an explicit atomic schema-extension group; validation checks the bounded combinations of those groups rather than the power set of individual fields.

Every agentic model identity carries a revision policy in addition to provider
and model id. `exact` requires a non-empty revision copied unchanged through
the immutable profile, capability certificate, execution binding, governed
recipe, provider request, and effective authority; authenticated live catalog
preflight must compare the provider's returned revision with that exact value
before transport. `provider_alias` is the explicit alternative for providers
whose public id is an alias: the policy and its certified catalog identity are
still pinned through those records, and the endpoint, resolved model, upstream,
and fallback constraints remain fail closed. Certificate/binding or
profile/certificate disagreement prevents authority creation. A legacy record
may hydrate only to the explicit `provider_alias` default as one atomic
digest-compatible schema extension; it does not become an exact revision claim.

Selectable agentic profiles bind their supported reasoning efforts and default into the immutable capability certificate and copy that exact contract into the session execution binding. `/api/providers` may use provider model metadata only for labels and descriptions; selectable values come from the active certificate. Chat renders a per-session reasoning selector only when that certified list is non-empty and does not recover missing choices from mutable model metadata. Before session creation and on every live certificate validation, Core rejects a requested effort outside the certified tuple or any mismatch between the certificate and binding. A behavior-changing built-in Codex adapter update publishes a new immutable profile revision and certificate, publishes a corresponding current binding for every enabled historical binding of the same model without rewriting the old binding, and suspends prior revisions whose adapter artifact digest is no longer current. A continuation selects the current enabled binding for the source profile/model; it must not silently move a historical non-default-model chat to the workspace default model. The declared Codex artifact bundle includes every app-server transport, thread, protocol, notification, steering, state, skill-input, configuration-policy, hook, reasoning, wrapper, sandbox, continuation-home, and legacy bridge module that can change provider behavior. Its revision-to-digest manifest is append-only: a historical digest may never be rewritten, and changing any declared artifact without adding a revision fails bootstrap and CI with `profile_revision_artifact_mismatch`. Codex profile revision 7 is the first revision certified against the expanded app-server bundle; revision 8 adds continuation-lineage ownership of the physical Codex conversation store and typed missing-thread failures; revision 9 adds admission/process fencing, live handoff revalidation, lineage snapshots, and sandbox-home identity; revision 10 binds orchestration decisions to live catalog snapshots; revision 11 adds remote-agentic containment gates at turn-queue admission and provider-start handoff; revision 12 binds turn-queue admission to the persisted provider-step quarantine/pairing gate without changing Codex execution semantics; revision 13 classifies terminal app-server overloads, drains the authoritative turn completion before detaching the event sink, and propagates the structured failure through the legacy bridge; revision 14 classifies terminal cybersecurity-policy blocks without exposing raw provider errors. In Chat's model menu each row presents the model label as its title, the provider label as its only subtitle, and the reasoning control inline at the right; rollout, certificate, tool-count, and technical profile badges do not belong in this compact picker.

The Codex app-server command for Maverick-managed runtimes must also disable Codex's built-in `apps` and `plugins` features. Runtime config preparation must write a managed Codex `[features]` section with `apps`, `plugins`, and `skill_mcp_dependency_install` disabled, instead of inheriting those feature switches from the operator home. Runtime-home preparation must remove plugin/app connector residue such as `plugins/`, `cache/codex_apps_tools/`, `.tmp/plugins/`, `.tmp/plugins.sha`, and `.tmp/app-server-remote-plugin-sync-v1` before launch so Codex does not attempt to start the `codex_apps` MCP bridge.

Maverick-managed Codex runtime config must also own provider-hook configuration. The adapter installs a runtime-local `maverick_codex_post_tool_use_hook.py` script under the session `bin/`, removes inherited operator-home `hooks.*` sections, enables the Codex `hooks` feature, disables `experimental_use_unified_exec_tool`, registers a Maverick-owned `[[hooks.PostToolUse]]` entry for supported shell tool names, and writes the matching Codex `hooks.state` trusted hash for that generated command identity. The hook calls Maverick's runtime-token provider-hook API and, for large or redacted shell output, returns `decision: "block"`, `continue: false`, and a compact replacement reason so Codex can continue from the compacted provider-history message instead of the original shell result when Codex accepts and runs the hook under its hook-trust policy. This is a Codex `Bash` hook integration, not a blanket claim for all provider tools or for sessions where Codex skips the hook.

Codex may also generate provider-bundled system skills under `CODEX_HOME/skills/.system` when app-server starts. Maverick-managed Codex runtimes must remove that provider-generated `.system` tree during runtime-home preparation and again after app-server initialization before starting or resuming a provider thread. The only runtime skills visible to Maverick agents are workspace-owned skill copies from the runtime session's selected `skill.catalog` provider and materialized by Maverick.

For sandboxed Codex sessions, sanitized runtime config must also drop inherited Codex `[projects.*]` trust entries that point outside the workspace root. This is provider-specific defense in depth: the generic Maverick runtime policy remains provider-agnostic, while the Codex adapter prevents Codex-specific trust configuration from weakening a Maverick sandbox.

For sandbox execution, the provider launch spec must carry both `readable_roots` and `writable_roots`.

For non-default workspace runtimes, both lists are exactly the workspace root.

The Codex provider must enforce that boundary before the app-server starts. It must launch the backend inside an operating-system workspace sandbox that mounts the workspace read/write, mounts only required runtime dependencies read-only, and does not mount the repository root, installation-level `core/`, installation-level `apps/`, another workspace, or operator home material.

The workspace operating-system sandbox may mount host resolver, host-name, NSS, and CA metadata as explicit read-only file binds when they are required for DNS or TLS. These file-level runtime dependencies do not broaden write access or expose workspace material outside the boundary. The sandbox must not mount broad host operating-system roots such as `/etc`, `/usr`, `/bin`, `/lib`, or `/lib64` by default. If a provider adapter explicitly supplies a dependency root for a concrete runtime binary, broad system document roots such as `/usr/share` and `/usr/local/share` must be masked so sandboxed agents cannot inventory host package documentation as user-accessible material outside the workspace.

When the configured Codex command is the NPM/NVM wrapper, the provider adapter should launch the packaged standalone Codex binary through a read-only bind at `runtime/bin/codex`. It must not mount the whole NVM installation, the whole Node version tree, or other operator-home package trees into sandboxed runtime sessions.

The same narrow binding rule applies to provider-bundled helper binaries that are required for normal workspace development. For Codex, `rg` must be exposed as a read-only file bind at `runtime/bin/rg` when the packaged ripgrep binary is available. The adapter should prefer the packaged standalone ripgrep binary over the `bin/rg` dotslash script, because sandboxed sessions must not require operator-home `dotslash` or package-manager trees. Exposing `rg` this way makes workspace-local search work without granting read access to the Codex package root, NVM installation, operator home, repository root, installation-level `core/`, installation-level `apps/`, or other workspaces.

Codex turn sandbox policy must keep writable roots constrained to the workspace while allowing provider network access. Codex app-server 0.130 and newer no longer accept `workspaceWrite.readOnlyAccess`; Maverick therefore relies on the operating-system workspace sandbox above to enforce the read boundary, and the turn payload must not send legacy `readOnlyAccess` or top-level `readableRoots`. The network permission is required for Codex app-server sampling, streaming, and explicit web-research tasks; it is not permission to broaden raw filesystem access beyond the workspace boundary.

If the host cannot create that read/write confinement, sandbox runtime launch must fail closed. It must not fall back to Codex `workspace-write`, legacy Landlock flags, or any mode that still permits raw reads outside the workspace.

It must not copy user-global, plugin-provided, or repository-local skills into the runtime home by default.

Maverick core has no preinstalled runtime skills. Skills are extension data owned by a workspace `skill.catalog` provider. The built-in Skills app is the canonical provider and seeds bundled skill templates from `apps/*/skills/` into `workspaces/<workspace_id>/data/skills/skills/` during install and migration. Another selected `skill.catalog` provider may own the same kind of editable catalog under its own workspace data root. Operators enable or disable workspace skill copies from that selected provider's editable workspace data.

At turn launch, the runtime materializes skills from the workspace-owned skill catalog selected for the runtime session. The canonical default provider is the built-in Skills app. If a runtime-owning app declares and selects a `runtime-skills` dependency for the `skill.catalog` interface, the runtime session must persist that selected provider app id and resolve both explicit `skill_ids` and implicit default skills from that provider's workspace data. Direct core runtime session creation through `/api/runtime/sessions` follows the same rule for the request `source_app_id` when that source app has a selected `runtime-skills` dependency, and may also accept an explicitly supplied `skill_catalog_app_id` only after validating that the app is an enabled `skill.catalog` provider in the workspace. `skill_activation_mode=implicit` preserves the legacy behavior: an empty `skill_ids` selection exposes every enabled skill and a non-empty selection narrows the catalog. `skill_activation_mode=explicit` keeps the automatic catalog out of the Codex prompt; a turn may supply only stable `invoked_skill_ids`, which core validates against the enabled catalog and any session allowlist before resolving a session-local materialized `SKILL.md` into a structured Codex skill input. A participant `skill_ids` snapshot is only an allowlist: static participant records, direct inter-agent messages, and persisted dynamic orchestration tasks carry their exact invocation set, never expand an empty request to the allowlist or catalog, and remain subject to the per-turn limit of 32. The adaptive planner receives a server-owned capability index. Every explicit non-empty allowlist is intersected with the currently enabled catalog before it is advertised; an empty intersection is reported as `none available`, while an enumeration failure is reported separately as `catalog unavailable`. Enabled IDs live in deduplicated shared scopes instead of being repeated per agent. Agent and skill pages share a global per-prompt character budget, advertise validated continuation cursors, and let the planner issue lookup-only JSON turns before producing a persistable plan or control decision. The initial planning turn may include one shared skill page; later safe points send only the bounded capability index unless the planner requests another page. Explicit tasks must choose their required subset from retrieved scope pages and failure feedback remains visible at the next control safe point. Successful same-turn steers atomically append their validated IDs to the turn receipt so compaction and backend-restart recovery preserve every skill activated during that turn. Missing legacy fields default to `implicit`; missing legacy participant invocation receipts default to an empty list; clients never supply filesystem paths.

Materialized runtime skills and rules must be copied into the session-local runtime home for sandbox sessions, not symlinked to source repository or operator home paths outside the workspace boundary. Explicit invocation must fail closed if the expected runtime copy is missing, is a symlink, or resolves outside `codex-home/skills`; absolute runtime paths must not be emitted in API payloads, transcript events, or logs.

Codex app-server retry notifications must be streamed as redaction-safe runtime step updates without prematurely closing the Maverick turn. Raw provider error envelopes and terminal provider errors are not chat-facing progress events.

Only terminal app-server failures should transition the runtime turn to failed. After a terminal error notification, the adapter must allow a bounded grace interval for the authoritative `turn/completed` notification so final usage and prompt-budget events are drained before detaching the event sink; if Codex omits that terminal notification, the bounded fallback must still unblock the turn. Structured provider error categories must propagate through the provider-neutral completion contract. In particular, Codex `serverOverloaded` maps to `provider_overloaded`, while `cyberPolicy` and `cyber_policy` map to `provider_cybersecurity_policy_blocked`; both use stable public copy rather than generic execution failure or raw provider text. Core must not automatically retry a provider policy block.

Core must not blindly replay an already accepted Codex turn after an overload because completed tool effects may already exist. Chat may offer an explicit user-triggered continuation that instructs the agent to inspect current state and avoid repeating completed actions; once later transcript work exists, that recovery action is no longer offered for the historical failure.

`codex exec` can be useful for isolated operator commands, tests, or one-shot automation, but it is not the product chat runtime because it does not preserve the provider conversation.

The canonical Codex runtime flow is:

1. runtime session starts
2. provider adapter launches `codex app-server --listen stdio://`
3. adapter sends `initialize`
4. adapter sends `thread/start` for a new provider conversation or `thread/resume` for an existing provider thread; any resume error fails explicitly and never falls back to `thread/start`
5. runtime turn submission sends `turn/start` with the provider thread id
6. while that regular turn is active, later admitted messages may send `turn/steer` with the expected provider turn id and `clientUserMessageId`
7. provider app-server emits structured turn, item, tool, and output events
8. runtime normalization persists provider events and accepted same-turn user messages as Maverick runtime events
9. WebSocket transport streams the persisted Maverick runtime events

Conversation memory for the active provider session comes from the provider thread.

Chat thread records and runtime event history are still persisted by Maverick for UI replay, audit, recovery, and app-owned metadata, but the Codex model context must be preserved through `thread/start` and `thread/resume`.

WebSocket delivery is the canonical realtime transport for active runtime turns.

The runtime WebSocket stream is the complete interactive history surface: the initial snapshot delivers a bounded hot tail, and explicit history frames page older persisted events. `GET /api/runtime/sessions/<session_id>/events` remains a diagnostics/operator endpoint and may expose only the bounded hot tail unless a separate paged HTTP contract is added. Live delivery must not poll the persistence adapter.

Runtime event recording has two distinct responsibilities:

- persist the event for replay, history, audit, and recovery
- publish the saved event to the in-memory runtime event bus for live subscribers

Provider output deltas may arrive as very small fragments. The runtime execution layer should coalesce adjacent output deltas before they reach runtime event persistence and live transport. Coalescing should be content-threshold based, not a tiny time-slice flush that turns slow provider tokens into one-character or one-syllable UI updates. Tool events, step updates, terminal events, and other non-output events must flush any pending output first so transcript chronology remains correct. Non-chat-facing command stream and terminal-interaction telemetry, such as Codex `item.commandExecution.outputDelta` and `item.commandExecution.terminalInteraction`, must be filtered rather than coalesced into persisted runtime history.

The WebSocket transport should subscribe to that bus before performing its initial replay so events recorded during replay are not lost. After replay, the WebSocket waits on the bus and sends events as they are published.

The local JSON persistence adapter is suitable for bootstrap control-plane state and runtime history replay. It is not a live token-streaming mechanism and must not sit in the active-turn hot path as a polling source.

For bootstrap deployments that persist runtime events in local JSON, event writes must be append-oriented. Saving one new runtime event must not require rereading and rewriting the full event history file, because active provider turns can produce many events while the HTTP host is also serving shell and app traffic. The bounded `events.json` hot tail may retain one additional bounded window between amortized compactions, while runtime store reads expose only the configured newest-event limit; reaching the logical tail limit must not turn every later event into a full-tail rewrite.

The local JSON adapter must treat malformed collection files as storage errors, not as empty collections. A corrupt runtime history file may require recovery, but it must not be silently overwritten in a way that makes existing chat threads appear empty.

Runtime session, turn, event, process, and state records must survive auth logout/login cycles and local host restarts.

Runtime turn cancellation is a persisted control-plane intent, not only an in-process provider callback. An interrupt publishes the first cancellation request before it waits for the session lifecycle handoff or invokes provider cleanup. Ordinary turn saves cannot clear that intent. Activation, provider start, and terminal transition reread it, cancellation wins over a later completion or failure, and repeated terminal reconciliation is idempotent. Plain-hosted requests also persist request-started and request-finished evidence with the owner kind, host, process id, process-start token, and per-request generation. The process that owns the HTTP response watches the durable intent and aborts the response, while HTTP, app, CLI, and MCP interrupt callers may wait for the persisted finished acknowledgement even when they run in another process. The waiter captures the exact turn and request generation, rereads that incarnation after waiting, and never treats an acknowledgement from another turn as success. Startup and interrupt-time reconciliation may close only an exact lease whose local process incarnation is proven dead; a different owner id alone is not evidence of death, and an unknown or foreign-host owner fails closed. Provider interruption is retried after the lifecycle transition so a handle registered during the acceptance handoff cannot escape cleanup.

Cancellation terminalization is a durable per-turn outbox. Its stable event id, event payload, event persistence, thread release, and source-app callback delivery are recorded as separate idempotent phases. Cancellation-intent ownership and terminal-outbox ownership are independent compare-and-set results. The durable intent CAS is the sole public ownership decision: among concurrent external interrupts, exactly its first claimant reports `interrupted=true`. The outbox CAS is technical only and never changes a public interrupt result, so a worker or a second caller may drain unfinished phases without creating another successful owner. Event persistence repairs history, bounded tail, and app-stream projections independently, so a crash between those writes does not turn a partial event into a permanent claim. Source-app callbacks receive the stable runtime event id and are delivered at least once: a crash or error before the delivered phase is persisted leaves the callback recoverable by a request retry or backend restart. A turn worker that observes cancellation before or during its own final transition drains this same outbox and never publishes a parallel terminal event or callback. Session cleanup and backend recovery use the authoritative turn status and the same cancellation terminalizer, so a concurrent completion never produces cancelled evidence.

For the local hosted bootstrap, workspace-scoped runtime-domain collections are persisted under the owning workspace root. Installation-local `.maverick/local-state/runtime/` is not the storage home for runtime sessions, runtime threads, turns, events, processes, or state.

This is a bootstrap adapter detail, not the domain model. Production deployments may replace it with MongoDB or another store adapter without changing runtime service interfaces.

Backend process restart is a runtime recovery event.

On real backend host startup, the platform must inspect persisted running runtime sessions. Generic platform-state bootstrap used by CLI wrappers, MCP wrappers, tests, app tooling, or other sidecar processes must not run backend-restart recovery, because those processes can coexist with live runtime workers owned by the backend host. The hosted backend must start this recovery from the backend host lifecycle without blocking the HTTP socket from opening; large runtime histories must not make the service unavailable while deterministic recovery work is still running. Recovery must scope bounded event reads to the running sessions being inspected instead of scanning every persisted runtime event partition or loading full legacy histories. Oversized valid event partitions may be skipped by the startup recovery scan, but they must remain in place for normal runtime history reads and WebSocket snapshot replay; malformed event partitions may be quarantined out of the startup path rather than parsed unboundedly. If a running session has a queued or active turn during true backend startup, the in-memory worker that owned that turn died with the previous backend process. The startup recovery pass must first reconcile the turn store with persisted terminal events. An explicit `runtime.turn.completed`, `runtime.turn.failed`, or `runtime.turn.cancelled` event closes the non-terminal turn record to match that evidence, dispatches the source-app runtime event hook for the terminal state, and does not enqueue a resume. `runtime.output.final` is successful completion evidence only when its `exit_code` is zero; a legacy event without that field retains completed semantics. A final-output event with a nonzero or malformed exit code never proves completion: when the canonical turn is still non-terminal at restart, recovery treats it as interrupted, preserves its partial output, records a visible failed event, and enqueues the bounded continuation. Remaining stale non-terminal user turns must be closed with explicit backend-restart evidence and source-app hooks must be dispatched for those terminal transitions. Before persisting a recovery message, Core validates the pinned live authority. Direct authority proceeds; a proven compatible profile change completes an idempotent continuation fork and resumes on the child session; an unproven change records `runtime.recovery.resume_blocked` without creating a turn. Each recovery message uses a deterministic client-message id derived from the interrupted source turn. If a recovery-created turn is itself interrupted by another restart, Core retries it up to three total attempts in that recovery chain. The terminal failed event states whether another retry was queued; after the limit it gives an actionable visible failure and records `runtime.recovery.resume_blocked` instead of creating an unbounded restart loop.

Recovery events, source-app callbacks, and resume eligibility must be derived
from the terminal status actually returned by the turn lifecycle transition,
not from its requested target. A persisted cancellation intent therefore
produces only `runtime.turn.cancelled` evidence and can never enqueue an
automatic resume. Before turn recovery, the new backend process also closes
unfinished plain-hosted request leases whose same-host process incarnation is
proven dead. Interrupt polling performs the same reconciliation so a CLI or MCP
owner that crashes after backend startup cannot leave a permanent phantom
acknowledgement. Each lease persists verifiable process identity and a
per-request generation; both dead-owner reconciliation and request-finished
acknowledgement compare-and-set the exact incarnation, so a late `finally` from
an older request cannot finish a replacement request on the same turn.
Before ordinary restart reconciliation, the backend also drains incomplete
cancellation outboxes for terminal turns, including sessions that no longer
have queued or active work. This repairs missing event, thread, and callback
phases without resuming cancelled work. A pre-outbox cancellation that already
has its legacy terminal event has event and callback delivery adopted without a
callback replay. Recovery then reconciles actual thread availability under the
session lifecycle handoff before marking the thread-release phase complete, so
the first deployment of the outbox format cannot leave a thread visibly active.
Recovery isolates terminalization failures per turn, and orchestration resume
still runs if the broader runtime recovery phase fails.

Hidden `inter_agent_participant` sessions are excluded from that generic
runtime `resume` behavior. Their interrupted turns are closed with explicit
restart evidence, after which `InterAgentService` marks the owning orchestrated
run `recovering`, persists a retry attempt for non-terminal task work, detaches
the old child session, and preserves completed task output. Only the real
backend host then enqueues the persisted orchestration scheduler, which creates
a recovery-generation child session and resumes dependency-ready work. CLI,
MCP, app tooling, and generic platform-state bootstrap must not enqueue these
workers.

Backend host startup is also the place for complete app/provider bootstrap. Sidecar CLI and MCP wrapper processes that only serve read-only discovery, inspect, SDK docs/templates, or developer-context commands should load the control-plane stores without reinstalling built-in apps, rerunning app hooks, registering provider definitions from heavy adapters, or bootstrapping admin credentials. A developer-wrapper sidecar outside a runtime session may fall back to app/provider bootstrap, without admin bootstrap, only when app discovery would otherwise read a control-plane with no persisted app sources or no enabled app bindings for the requested workspace; this avoids returning false empty discovery on a fresh local control-plane. Mutating sidecar commands may request full bootstrap when they need host-side app/provider state creation.

After runtime turn reconciliation, backend restart recovery may invoke generic background hooks declared by enabled workspace apps. The hosted backend may also run a periodic app-agnostic `background_tick` hook scheduler for active workspaces. The core must not know what those apps are recovering or scheduling. It only invokes the declared hook, publishes declared app events, and applies any permitted generic runtime session or interrupt requests returned by the app. App-specific recovery decisions, such as whether a queued app-owned workflow node should launch after a browser was closed, remain app-owned backend behavior.

One background tick resolves each enabled workspace app surface at most once and reuses that tick-local contract snapshot while matching all dependency interfaces. It must not reread and reparse the complete app catalog separately for every dependency alias. Prepared-session cleanup likewise reuses its candidate snapshot between bounded attempts, revalidates the selected session under the lifecycle handoff, and avoids a second installation-wide scan when the pool is already clean. The cleanup phase is offset from the app-hook interval so periodic maintenance tasks do not intentionally synchronize their filesystem work and contend with interactive runtime requests.

Runtime JSON partitions may be touched by the backend host and sidecar runtime processes. Session-partitioned collection reads and writes must use a filesystem-level lock, not only an in-process mutex, so append-only event writes, pruning rewrites, and recovery reads cannot interleave into malformed JSON. Workspace-scoped collection queries must enumerate only that workspace's session partitions, and bulk session reads must retain the resolved workspace partition before projecting provider state so one catalog request does not repeat installation-wide filesystem discovery for every session.

This behavior is deterministic platform recovery. It must not depend on frontend reconnect timing, agent-specific logic, or a user manually sending another message.

Runtime session persistence must include enough provider binding state to resume a provider conversation when the provider supports it.

For Codex this means storing the app-server thread id returned by `thread/start` and reusing it with `thread/resume`.

If a provider cannot resume native conversation state, its adapter must make that limitation explicit and choose a documented fallback such as reconstructing bounded conversation context from runtime events.

Chat thread records may reference runtime session ids, but chat history rendering must load authoritative runtime events from the runtime surface.

For chat UI state, `runtime.output.final` is terminal evidence for the active turn even if `runtime.turn.completed` is delayed, dropped by the active WebSocket, or replayed out of order.

The runtime store should still record explicit terminal turn events, but the chat frontend must clear its busy/stop state once final output for that turn is present.

Terminal turn evidence must also dominate earlier or late-arriving `queued` or `started` events for the same turn so replay ordering cannot reactivate a finished turn.

If a provider emits session-level terminal evidence without a `turn_id`, chat replay must close the latest active turn for that session rather than leaving the transcript in a permanent loading state.

Live loading labels must be derived only from runtime step events for the active turn. Historical step labels from earlier turns, including failure text, must not be reused as the current `Thinking` label for a later or idle turn.

Transcript rendering must also close active tool indicators when later output, final output, failure, or cancellation proves the turn has moved past that tool. A tool may be shown as actively running only while it is the latest evidence for an active turn.

Chat transcript rendering must preserve the runtime event ordering for visible tool usage.

Streamed assistant output is part of that same event timeline. When a later `runtime.output.final` arrives, the chat renderer must use it as terminal evidence and as a source for any missing suffix or structured link previews, but it must not replace already-rendered output segments in a way that moves tool groups above or below the text updates that originally separated them.

The runtime must not persist the same assistant text twice as transcript segments. `runtime.output.delta` carries progressive assistant text. `runtime.output.final.payload.text` is terminal transcript evidence and may carry only the text suffix that was not already emitted through deltas. If the provider's final text is exactly the concatenation of streamed deltas, the final event must use an empty `text` field.

`runtime.output.final.payload.complete_text`, when present, is a separate consumer contract rather than an additional transcript segment. It carries the complete final assistant answer assembled from streamed deltas and final text for consumers that need one explicit final value, such as inter-agent participant completion readers, backend restart recovery, and source-app lifecycle hooks. Renderers must not append `complete_text` to the transcript after already rendering deltas; they should continue to use `text` for the terminal suffix behavior above.

This deliberately allows a final event to be larger than the suffix-only transcript payload, because `complete_text` can duplicate assistant text already stored in prior deltas. Generic runtime output compaction currently targets `runtime.tool_call.*` payloads, not `runtime.output.final`; the accepted tradeoff is that final-answer consumers get an explicit complete value while transcript renderers preserve non-duplicating delta/final chronology. Any future compaction or size cap for `complete_text` must preserve the suffix-only `text` contract and provide an equally explicit complete-answer source for inter-agent and recovery consumers.

Consecutive runtime tool-call invocations within one turn may be rendered as a single `Tool Used` group, with start/update/completion events for the same invocation merged inside that group only when the provider supplies a stable call id such as `tool_call_id`, `call_id`, or `item_id`.

The renderer must not merge separate invocations merely because they use the same tool name or command.

A visible runtime update, output, failure, cancellation, or other non-tool transcript event must close the current tool group.

If more tool calls arrive after that update, chat must render a new `Tool Used` group rather than appending those later tools to an earlier group.

Provider notifications that describe a concrete runtime capability change may also be projected into the `Tool Used` affordance when that gives the user a better audit trail than a plain step label.

For example, a `skills changed` runtime update may be rendered as a synthetic `skill_change` tool item while preserving the original runtime event payload in the tool detail panel.

Deleting a chat thread is also a runtime ownership operation when the thread references a runtime session.

The chat product model is one logical runtime-thread invariant. Ordinarily one chat maps to one `session_kind=chat_root` runtime session, one selected-provider app-server context, and one canonical session root under `workspaces/<workspace_id>/runtime/sessions/<runtime_session_id>/`. When immutable execution authority changes compatibly, the same thread may point to a child runtime session and render the frozen predecessor plus child as one audited lineage. Automatic forks are limited to `chat_root`; hidden inter-agent and system sessions fail closed because their scheduler ownership would require a separate audited handoff. Continuation admission holds the same per-session message-admission and lifecycle fences used for ordinary turn creation. Any queued, active, or waiting turn on the predecessor or successor blocks ownership transfer. The predecessor keeps its original binding and history, rejects new turns, and is not listed as a second chat. For Codex, the provider thread id and its physical database/rollout store move as one ownership unit: the executable child uses the lineage-root `CODEX_HOME`, and Core must prove the predecessor app-server process is absent before transferring provider state or starting the child. A chat thread must not exist without a user-visible current runtime session, and every current `thread_visibility=user` runtime session in the active workspace must be represented by exactly one runtime thread before the chat list is returned. `thread_visibility=hidden` sessions are runtime-operational records for future inter-agent participants and must not appear as standalone chats. The initial runtime thread id should use the initial runtime session id; continuation rebinds only its `runtime_session_id` pointer so the user-facing thread identity remains stable. Runtime WebSocket snapshots carry the requested logical session id plus all physical lineage ids; Chat scopes events to that authenticated set and follows a live `runtime.continuation.forked` event onto its successor instead of discarding child events as foreign.

Chat may keep one hidden prepared `chat_root` session for the next draft. Its idempotency fingerprint is computed after session admission from both normalized request configuration and the resolved immutable execution-binding identity, including binding revisions and the effective reasoning effort. Omitting a reasoning effort and explicitly selecting the certificate default therefore reuse one prepared session, while a real profile or binding revision cannot reuse a stale pin. The browser derives that effective default before launching preload work so React state settlement does not issue an abandoned first request with an equivalent configuration.

Every resumed handoff revalidates the source and successor certificates,
workspace bindings, credential availability, egress governance, adapter
artifact digest, and persisted compatibility proof against current live
authority before another phase advances. An expired or artifact-stale
intermediate target may be completed only as a fenced link and immediately
continued to the newest compatible revision; admission follows at most a
bounded number of such links and succeeds only on a direct current target. A
revoked or otherwise incompatible successor is quarantined as non-executable
and the handoff fails closed without moving provider state.

Session reads expose the redaction-safe admission states `direct`,
`compatible_upgrade`, `upgrade_required`, and `provider_thread_missing`. Chat may
keep the composer active for the first two because submission can complete a
proven compatible fork; it blocks the latter two with actionable copy and must
not imply that an unavailable provider conversation can be reconstructed.

Bulk repair is an admin-only CLI operation and defaults to `dry_run=true`.
Inventory resolves a requested predecessor or lineage root to its current tip
and deduplicates multi-hop lineages. Before a mutating run, Core writes a
private, collision-safe snapshot under `data/recovery-snapshots/` containing
provider control-plane JSON, workspace runtime indexes, every selected lineage
session's JSON/event-history records, and the Codex lineage-root conversation
store required to resume it. SQLite databases are copied through SQLite's
online backup API and pass `PRAGMA quick_check`; rollout JSONL files are copied
with canonical-path and symlink checks, bounded size, and SHA-256 entries in the
manifest. Logs, transient caches, and unrelated provider homes remain excluded.
The mutation then uses the same preflight inventory and never broadens its
session scope between snapshot and handoff.

The core owns the delete operation. `DELETE /api/runtime/threads/<thread_id>` removes the core thread record and performs full cleanup of the linked runtime session. `POST /api/runtime/threads/delete-batch` accepts up to 20 deduplicated thread ids, authorizes every resolvable thread before mutation, expands root and active inter-agent child sessions once, and returns an explicit `deleted` or `not_found` result for every requested id. `POST /api/runtime/threads/clear` applies the same batch cleanup operation to every runtime thread in the active workspace.

A synchronous thread-delete batch invokes each eligible app cleanup callback once with the complete deduplicated session-id list, including every continuation predecessor, deletes the selected thread records with one collection mutation, and publishes one workspace thread-catalog delta. Direct chat cleanup, Settings cleanup, and authorized app cleanup requests use the same lineage expansion, so no surface may delete only the current child and orphan its predecessor or handoff record. Physical runtime cleanup remains complete before the response; batching must not weaken process termination, authorization, hidden-session policy, or canonical-root safety.

Runtime persistence adapters expose multi-record deletion so shared workspace or control-plane collections are read and rewritten once per session batch rather than once per matching record. Session-partitioned event archives are removed as files; cleanup must not decode complete historical archives solely to produce a deletion counter before deleting the same canonical session root.

The chat app must not implement a parallel thread delete path, return cleanup requests, or rely on hidden app-specific side effects in the platform app mount.

The runtime cleanup endpoint must remove the runtime session completely.
That includes terminating any live provider subprocesses registered for that runtime session, cancelling queued or active turns, deleting runtime-session records, deleting linked core runtime thread records, removing canonical runtime files, and invoking app-declared cleanup hooks for app-owned data linked to that runtime session.
Process termination remains a core runtime responsibility, but app-owned cleanup must be exposed through generic lifecycle orchestration rather than through app-specific platform-host behavior.

Apps that own runtime-linked metadata or files must opt in with `permissions.runtime.receive_cleanup_callbacks` and expose the declared cleanup backend action.
The core invokes every enabled opted-in app with a generic context containing `workspace_id`, `local_app_id`, `public_app_id`, the deduplicated `runtime_session_ids`, and canonical runtime paths.
The app decides how to clean its own records under `data/<local_app_id>/`, and the hook must be idempotent, bounded by hook timeout, and governed by the same app contract and workspace authorization rules as other lifecycle hooks.

Therefore a persisted core chat thread must not outlive its runtime event history in a way that silently appears as an empty new chat.

Runtime turn state must remain consistent across the turn store and runtime event log. If startup recovery finds a non-terminal turn event without a corresponding turn record, it must append a terminal recovery event for that turn id so event-based transcript rendering and turn-based availability checks do not disagree indefinitely.

The WebSocket transport must support:

- workspace/session authorization during handshake
- ordered initial replay from persisted runtime events
- push delivery for newly recorded runtime events through the runtime event bus
- replay from a client-provided last seen event id
- heartbeat or keepalive messages that are transport-level, not runtime-domain events
- clean terminal delivery for completed, failed, cancelled, or timed-out turns

HTTP event replay is a recovery and history surface, not the active-turn transport. Polling the event store during a live WebSocket session is not an acceptable implementation of realtime streaming. SSE is not the target first-class transport unless a future deployment environment makes WebSocket impossible.

#### Runtime process

A runtime process is the execution handle that a runtime session currently controls.

For the first implementation, the runtime process model should support local process execution cleanly.

The model should not assume that every runtime must always be a local subprocess forever.

That said, remote-node or distributed-runtime orchestration is not required to complete the first local Phase 6 implementation.

The first local implementation should still model process lifecycle states explicitly, for example:

- `created`
- `running`
- `exited`
- `failed`
- `terminated`
- `timed-out`

#### Runtime state

Runtime state is the mutable execution snapshot of one runtime session.

Examples:

- current turn pointer
- last known progress
- watchdog state
- forced stop reason
- last runtime error detail

This state belongs to the runtime domain, not to chat persistence and not to app-owned storage.

### `inter_agent/`

Owns:

- delegation
- inter-agent message transport
- queueing
- retries
- delivery reconciliation
- coordination state
- policy-aware participant runtime-session spawn, send, wait, interrupt, resume,
  close, cleanup, and startup recovery orchestration

This package should be explicitly separate from `runtime/` even when the two collaborate closely.

### `providers/`

Owns:

- provider definitions
- provider adapters
- provider selection
- model capability metadata
- provider credential resolution

This package should make it possible to support:

- Codex
- Claude Code
- Kimi
- local open-source runtimes
- API-key based hosted models

without changing workspace or app architecture.

### Provider boundary rules

The provider domain should stay separate from:

- runtime session lifecycle
- workspace filesystem routing
- HTTP settings routes
- UI-specific forms or settings payloads

Provider modules should answer questions such as:

- what provider definitions exist
- what capabilities each provider offers
- what secret bindings or credential references are required
- how one runtime backend is constructed or selected

They should not become a generic dumping ground for runtime control logic.

### Provider definitions versus credentials

Maverick should distinguish clearly between:

- provider definition
- provider capability metadata
- provider credential binding
- runtime backend selection

Those are related, but they are not the same record.

The definition says what the provider is.

The capability metadata says what it can do.

The credential binding says which secret or operator-managed credential is attached.

The runtime backend selection flow decides which backend the runtime should use for one execution context.

Generic runtime turn submission, same-turn message admission, execution, user interrupts, app-requested interrupts, and cleanup must depend on the selected runtime backend adapter, not on Codex-specific branches. The runtime domain may coalesce and persist provider-neutral events, but backend launch specs, subprocess/protocol execution, provider thread binding, same-turn input, turn interruption, and provider runtime cleanup belong to the adapter registered for the selected provider.

Raw secret values must not appear in domain models or ordinary runtime records.

### Provider kinds

The provider abstraction should support at least two architectural kinds:

1. runtime-style backends
2. hosted API-style providers

Examples:

- `Codex`, `Claude Code`, `Kimi`, and local OSS runtimes behave like runtime-style backends
- hosted model APIs behave like API-style providers

The first implementation may ship only one real backend, but the core model should not collapse those categories into a single provider shape.

The current implementation ships:

- a provider registry owned by `core/providers`
- provider definition records separated from credential bindings and workspace selection records
- a workspace-aware provider selection flow in the core
- a runtime backend adapter contract that owns launch-spec construction, skill materialization, turn execution, optional same-turn input, turn interruption, and provider runtime cleanup
- one concrete runtime backend adapter: `Codex`

`Codex` is therefore the first installed backend, not the architectural identity of the provider layer.

Provider definition registration must stay cheap enough for bootstrap and discovery processes. Expensive dynamic catalog probes, such as Codex `debug models`, must not run merely to register built-in providers or list CLI/MCP command surfaces. Those probes belong to provider settings, provider configuration validation, runtime launch, or explicit health/diagnostic flows, and should use a bounded cache or TTL so repeated settings reads do not spawn provider binaries unnecessarily.

### `execution_policy/`

Owns:

- sandbox policy
- full-access policy
- boundary validation

### `secrets/`

Owns:

- secret storage interfaces
- secret resolution
- binding logic
- grant policy for app-scoped use

The secrets layer should distinguish clearly between:

- secret metadata and bindings
- grants and policy decisions
- raw secret values

The domain and service layers should work primarily with references, bindings, aliases, grants, and resolution results, not with persistent raw secret payloads.

Raw secret values must stay confined to controlled secret-store adapters and short-lived runtime delivery paths.

The first implementation supports:

- platform-owned secret records and aliases
- workspace-scoped, app-scoped, or provider-scoped secret bindings
- app-scoped grants with logical names, action allowlists, structured HTTP/HTTPS or platform delivery target patterns, expiry, revocation, and actor metadata
- controlled resolution for runtime use
- app-scoped secret write and rotation requests from mounted app backend entrypoints, including optional `resource_type` and `resource_id`, with raw values stripped before frontend responses and explicit audit/event records for automatic secret create, rotate, and delivery-grant creation
- grant-based ephemeral delivery into mounted app backend, CLI, and MCP entrypoint payloads for grants that allow the `app.backend` action, match the synthetic delivery target, and whose logical names are declared by the app contract; backend delivery uses `maverick://app.backend/backend` and may narrow to `maverick://app.backend/backend/<resource_type>/<resource_id>`, while CLI and MCP use per-entrypoint targets such as `maverick://app.backend/cli/<command>` and `maverick://app.backend/mcp/<tool>` and receive only logical names explicitly listed in that command or tool descriptor's `required_secrets`
- admin HTTP surfaces for Vault to list metadata, create/import values, rotate, disable, revoke, manage grants, and inspect audit history without returning raw values
- ephemeral secret delivery into provider launch paths under platform authority
- operator inspection of metadata without exposing raw values
- operator-facing CLI and policy-gated MCP hooks for inspection and full-access create, rotation, disable, and revoke operations without ever returning raw secret values; official Core CLI/MCP secret grant surfaces list, create, and revoke grants, list grant targets, expose recommended grant specs derived from app contracts and descriptors, and list redaction-safe secret audit records
- audit records for create, rotate, disable, revoke, grant creation, grant revocation, resolve allow, and resolve deny

Grant creation must validate that the referenced secret exists and is active, the target app is installed, enabled, and surface-resolvable in the current workspace, `app.backend` logical names are declared by the target app under `permissions.secrets.read`, the logical name is unique among non-expired active grants for that app, optional expiry is in the future, and target patterns are either `*`, normalized HTTP/HTTPS URL patterns without query strings or fragments, or the platform delivery target family `maverick://app.backend/*`. Resource-specific platform delivery target patterns must match the grant's own `resource_type` and `resource_id` scope. Empty or omitted target patterns may default to `*` only for internal `app.backend` delivery grants; external or user-directed actions such as browser autofill require explicit target patterns. `*` is valid only for single-action grants; mixed-action grants must use explicit target patterns because targets are grant-wide rather than per-action. Query strings supplied by runtime targets are ignored for matching and stripped from persisted audit payloads. Creating a secret refuses existing secret ids and aliases; value replacement must use rotation. Disabling or revoking a secret explicitly revokes active grants linked to that secret in the secret service layer, regardless of whether the mutation came through HTTP, CLI, MCP, or another core caller, and records cascade audit entries in each impacted grant workspace when an audit-capable surface is present. Secret grant target discovery belongs to an admin-only Core Secrets surface such as `/api/secret-grant-targets`; generic workspace app registry responses such as `/api/apps` must not expose secret permission logical names.

Secret value envelopes use authenticated encryption. The JSON control-plane adapter stores values as AES-GCM envelopes with a value format, nonce, ciphertext, and key id; AAD binds the ciphertext to the value format, secret id, and key id. The active key comes from the operator-managed secret-store key material, and `MAVERICK_SECRET_STORE_PREVIOUS_KEYS` may provide previous decrypt-only keys during rotation. Legacy `mvr3secret1` values remain readable for migration.

#### Recommended first file layout

```text
secrets/
  models.py
  errors.py
  store.py
  secret_store.py
  secret_bindings.py
  grants.py
  target_policy.py
  policy.py
  secret_resolution.py
  service.py
api/
  secret_api.py
```

Suggested responsibilities:

- `models.py`
  - `SecretRecord`
  - `SecretBindingRecord`
  - `SecretGrantRecord`
  - `ResolvedSecretLease` or equivalent short-lived resolution result
- `store.py`
  - storage-agnostic store contracts
- `secret_store.py`
  - concrete secret persistence and encryption adapter wiring
- `secret_bindings.py`
  - binding and alias logic separate from raw value persistence
- `grants.py`
  - grant creation, validation, listing, and revocation logic
- `policy.py`
  - action, target, app, workspace, expiry, and grant-status checks before resolution
- `target_policy.py`
  - structured target normalization, matching, and audit-safe target redaction
- `secret_resolution.py`
  - controlled runtime resolution and delivery logic
- `service.py`
  - orchestration across store, bindings, and resolution
- `api/secret_api.py`
  - admin-only HTTP surface used by Vault and platform UI clients; responses contain metadata or redacted leases only

### `recovery/`

Owns:

- restart logic
- failed state handling
- repair orchestration at platform level

Recovery is not just "restart the process".

The platform should distinguish between:

- restartable failures
- repair-first failures
- non-recoverable failures that require operator action

So the recovery layer should coordinate:

- runtime restart intents
- backend-startup recovery for interrupted runtime turns
- failed-start diagnosis
- health-driven recovery decisions
- backend downtime watchdog escalation into an autonomous full-access rescue agent after sustained outage
- operator-facing repair and recovery workflows exposed through controlled CLI or MCP surfaces

The recovery surface should be designed so that operators can still reach it even when the main backend surface is unhealthy or unavailable.

In practice, this means the recovery domain should stay separable from the primary application host lifecycle.

The first implementation does not need a fully separate deployment, but it should preserve a clean boundary so that a dedicated recovery service or recovery-only host can be introduced without redesigning the domain.

The first implementation should also expose recovery through controlled CLI and MCP hooks so operators can:

- inspect recovery state
- record failed-start diagnoses
- execute runtime restart through the runtime lifecycle when the platform can reach the runtime store
- run on-demand runtime, provider, and app health probes
- plan restart or repair-first recovery intents

The explicit backend host restart surface is narrower than the rest of the recovery domain. `core.recovery.restart_backend` is governed by a dedicated admin recovery capability, such as `recovery.restart_backend`, and must be authorized from trusted platform or workspace governance records. `full-access` execution in the `default` workspace is only the filesystem/process mode needed to perform the restart; it is not itself proof of authority. Runtime callers without that admin capability must be denied, including full-access default-workspace agents that are not explicitly granted the capability.

App health probes should execute through the installed app's declared health contract or health hook when one exists, without relying on caller-supplied booleans, app-owned shortcuts, or direct access to primary backend runtime internals as the source of truth.

Backend downtime escalation is intentionally outside the main backend process. The watchdog owns only health probing, persisted downtime state, cooldown, and launch control for a single rescue agent. The rescue agent owns diagnosis and the minimal forward code or deployment fix. The backend startup recovery pass owns runtime session spin-back after the main service is healthy again.

Automatic backend downtime escalation is separate from manual restart authority. The watchdog is a full-server infrastructure service and may launch a rescue runtime only through the configured recovery provider. Manual restart remains an admin-governed operation and must not use `full-access/default` as a shortcut around capability checks.

#### Recommended first file layout

```text
recovery/
  models.py
  errors.py
  store.py
  runtime_recovery.py
  failed_start_recovery.py
  backend_watchdog.py
  health_checks.py
  service.py
  routes.py
```

Suggested responsibilities:

- `models.py`
  - failure classifications
  - recovery intent records
  - health result summaries
- `store.py`
  - persistence contracts for recovery markers and health snapshots when needed
- `runtime_recovery.py`
  - restart or resume orchestration for runtime sessions
- `failed_start_recovery.py`
  - diagnosis and recovery planning for startup failures
- `health_checks.py`
  - runtime, provider, and app health probe orchestration
- `service.py`
  - platform-level recovery coordination
- `routes.py`
  - CLI or MCP surface wiring for controlled recovery operations

### `observability/`

Owns:

- structured platform events
- runtime observability
- platform logging and audit hooks

The observability layer should keep these concerns distinct:

- raw log streams
- structured platform and runtime events
- audit records for operator-relevant control-plane actions
- metrics suitable for health and supportability workflows

Every operation that changes control-plane state or crosses a trust boundary should emit structured observability.

The audit record is the governance trail.

The structured event is the operational timeline.

Runtime and app logs are supporting debug streams, not the source of truth for governance.

The first implementation should wire audit and structured event emission into the real core flows, especially:

- app source registration, install, enable, disable, fork, rebase, upgrade, rollback, uninstall, purge, and reinstall
- frontend, backend, CLI, MCP, and skill mounting or unmounting
- app-owned CLI and MCP invocation failures, policy denials, and entrypoint execution failures
- provider binding, selection, launch-spec construction, credential binding, and provider health probes
- secret create, rotate, resolve attempts, denied resolution, disable, and revoke surfaces
- runtime session creation, lifecycle transitions, provider launch, process failure, and execution policy decisions
- workspace export, app export hook execution, manifest generation, import, and restore
- recovery health probes, recovery intents, actions executed, and actions failed

Observability data must be attributed consistently across planes, for example with:

- `workspace_id`
- `app_id`
- `runtime_session_id`
- `turn_id`
- `provider_id` when relevant
- source domain or component

Observability must also enforce redaction rules so that logs, audit trails, and structured events do not leak:

- raw secret values
- raw provider credentials
- sensitive runtime environment payloads unless explicitly allowed by operator policy

The first implementation should create and manage:

- installation-level log roots under `logs/platform/` and `logs/runtime/`
- workspace log roots under `workspaces/<workspace_id>/logs/workspace/`
- app-local log roots under `workspaces/<workspace_id>/logs/apps/<app_id>/`

It should also exclude workspace logs from default workspace export manifests.

#### Recommended first file layout

```text
observability/
  models.py
  errors.py
  store.py
  event_log.py
  audit_log.py
  runtime_log.py
  metrics.py
  service.py
  routes.py
```

Suggested responsibilities:

- `models.py`
  - structured event records
  - audit records
  - metrics envelopes or counters when modeled in code
- `store.py`
  - storage contracts for event, audit, and metric persistence
- `event_log.py`
  - structured event emission and attribution helpers
- `audit_log.py`
  - operator-relevant control-plane audit recording
- `runtime_log.py`
  - runtime-engine and process log handling
- `metrics.py`
  - metrics collection and aggregation surfaces
- `service.py`
  - redaction-aware orchestration across observability planes
- `routes.py`
  - operator inspection surfaces where intentionally exposed

### `mcp/`

Owns:

- MCP host surface
- tool registry
- platform MCP wiring
- app-facing runtime MCP boundaries

The core MCP layer should keep tool registration separate from transport bootstrap.

The registry of available tools, their schemas, and their discovery metadata should not be entangled with HTTP mounting, stdio startup, or application entrypoint wiring.

This keeps MCP bootstrap logic out of the main application startup path.

The core MCP layer is a platform-managed host for both:

- core-owned tools
- app-contributed tools from enabled workspace apps

The app contract may declare MCP capability surfaces, but the core still owns whether and how those surfaces are mounted.

MCP invocation policy should be enforced by the platform host in the same spirit as controlled CLI entrypoints.

So a tool being visible in discovery metadata is not, by itself, sufficient authority to execute it.

In the first local implementation, app-owned MCP entrypoints are invoked by the platform through a deterministic subprocess contract:

- the core resolves the declared entrypoint path
- the core passes a JSON payload on standard input
- the entrypoint returns a JSON object on standard output
- the entrypoint runs with the same Python interpreter as the core process unless a future runtime-specific interpreter strategy is introduced

This keeps mounting and policy centralized in the core while still allowing app-owned MCP logic to execute for enabled apps.

App-owned MCP tools should be namespaced in the platform host, for example:

- `app.<app_id>.<declared_tool_name>`

This prevents collisions between app-owned tools and core-owned tools in the shared host surface.

### `cli/`

Owns:

- platform CLI commands
- workspace and app administration commands
- operational maintenance commands
- batch and scriptable control surfaces

The core CLI is an official runtime and workspace automation surface.

CLI commands are agent-invokable by default when the trusted workspace context, execution mode, and command-specific policy allow the operation. The CLI layer must not use an `operator-only` category; privileged operations are expressed with workspace context, full-access mode, platform/workspace role checks, or domain-specific authorization inside the handler.

That means the CLI layer must distinguish clearly between:

- workspace-context commands
- full-access commands
- commands that may be surfaced through both CLI and MCP with separate policy models

CLI command registration should stay separate from invocation policy.

Whether a sandboxed agent may invoke a command is a core policy decision, not something inferred only from raw command-line arguments.
When an enabled app needs a per-command policy override, the core may read an app-owned `cli/command_policies.json` manifest beside the declared CLI entrypoint. That manifest can tighten visibility for declared app commands, for example by requiring a platform role, without adding app-id-specific branches to the core CLI registry. The manifest is not a replacement for core enforcement: the core still owns policy parsing, validation, discovery filtering, and invocation denial.

The same CLI framework should be able to host both:

- core-owned commands
- app-contributed commands for enabled workspace apps
- core-owned per-app lifecycle commands for app installation, uninstallation, and complete workspace-local removal when those operations are available

The core remains responsible for command registration, workspace authority checks, and exposure policy.

The user-facing Maverick wrapper must keep discovery scoped by authority and owner. `maverick apps list --json` is the compact app-discovery command. Core-owned CLI commands are discovered and invoked through `maverick core cli list --json`, `maverick core cli inspect <command_id> --json`, and `maverick core cli run <command_id> ...`. App-owned CLI commands are discovered and invoked through `maverick app <app_id> cli list --json`, `maverick app <app_id> cli inspect <command_name> --json`, and `maverick app <app_id> cli run <command_name> ...`. Official app frontend rebuilds use `maverick app <app_id> frontend build --json`, which runs the core app-hosting frontend build operation and emits the mounted-frontend refresh event after success. The wrapper must not provide a default global command dump that merges all core and app commands, because agents should pull only the command surface relevant to the task.

For local sidecar invocations, read-only wrapper commands such as `apps list`, CLI/MCP `list` and `inspect`, SDK docs/templates, and developer-context reads must not perform the backend host bootstrap path when usable app/provider state already exists. They should use the existing persisted control-plane state. Outside a runtime session, app-dependent discovery may perform one app/provider bootstrap, still without admin bootstrap, when persisted app source and binding state is absent for the requested workspace, because returning an empty app surface from a never-initialized control-plane is not authoritative. Runtime agents should normally reach these commands through the runtime HTTP shim rather than through the developer wrapper.

Canonical coding guidance for workspace agents must also be exposed through read-only core developer-context surfaces. `maverick core cli run developer-context.list --json` returns the canonical developer document catalog, and `maverick core cli run developer-context.read --doc-id <doc_id> --json` returns one canonical document body at a time. This lets sandboxed workspace agents read `AGENTS.md` and selected architecture documents without direct filesystem reads outside the workspace boundary.

MCP follows the same scoped discovery rule. Core tools use `maverick core mcp list --json`, `maverick core mcp inspect <tool_name> --json`, and `maverick core mcp call <tool_name> ...`. App tools use `maverick app <app_id> mcp list --json`, `maverick app <app_id> mcp inspect <tool_name> --json`, and `maverick app <app_id> mcp call <tool_name> ...`. The core developer-context tools `developer-context.list` and `developer-context.read` expose the same canonical document catalog and one-document read contract over MCP. `--help` remains human-oriented parser help; `list` and `inspect` are the machine-readable discovery contract for agents.

Per-app lifecycle CLI commands use the app namespace but remain core-owned operations. They do not require each app to implement its own install or uninstall script. `app.<app_id>.install` is available when a platform app source or workspace-local project exists. `app.<app_id>.uninstall` is available when the app has a workspace binding. `app.<app_id>.frontend.build` is available when the enabled app declares a frontend entrypoint and has a real frontend build script. `app.<app_id>.sidecars.restart` is available only for an enabled binding with declared sidecars; it revokes browser authority for that app/workspace, restarts only its declared processes, waits for readiness, audits safely, and emits the scoped runtime/frontend-changed event. `app.<app_id>.remove` is available only for workspace-local app projects, because complete removal deletes workspace-owned source and data rather than merely detaching a binding.

In the first local implementation, app-owned CLI entrypoints follow the same deterministic subprocess contract:

- the core resolves the declared CLI entrypoint path
- the core passes trusted invocation context, including `workspace_id`, `agent_id`, `effective_mode`, and `runtime_session_id` when available, plus app arguments as JSON on standard input
- the command returns a JSON object on standard output

Implementation files should keep command ownership explicit.

Recommended CLI split:

- `core_commands.py` composes core-owned command groups
- `workspace_commands.py` owns workspace inspection commands
- `runtime_provider_commands.py` owns runtime and provider commands
- `secret_commands.py` owns secret management commands
- `recovery_commands.py` owns recovery commands
- `app_lifecycle_commands.py` owns core-managed per-app lifecycle commands
- `app_commands.py` owns enabled-app command mounting
- `registry_builder.py` builds the visible command registry and runs commands

`service.py` may remain as a small public facade, but it should not accumulate registry, policy, and execution logic.

Recommended MCP split follows the same shape:

- `core_tools.py` composes core-owned tool groups
- `workspace_tools.py` owns workspace registry tools
- `runtime_provider_tools.py` owns runtime and provider tools
- `secret_tools.py` owns secret management tools
- `recovery_tools.py` owns recovery tools
- `app_tools.py` owns enabled-app tool mounting
- `registry_builder.py` builds the visible tool registry and invokes tools

This prevents the core surfaces from becoming mixed registry/spec/execution monoliths.

### `skills/`

Owns:

- core-owned procedural skills
- guidance for using the core's MCP and CLI correctly
- reusable operational workflows for orchestration, inspection, recovery, and provider setup

This does not refer to the separate app named `Skills`.

It refers to instruction assets owned by the core itself.

Core skills may be loaded, indexed, or synchronized into runtime-adjacent locations when necessary, but they remain instructional assets.

They do not become executable capability surfaces merely because they are materialized for runtime use.

Runtime authority and policy enforcement must continue to live in MCP, CLI, provider, runtime, and backend service layers rather than in `skills/`.

The skill catalog is platform-managed and may include:

Enabled workspace-owned skills from the runtime session's selected `skill.catalog` provider, optionally narrowed by explicit session `skill_ids`. The built-in Skills app is the canonical default provider.

How those skill assets are installed into a runtime home is provider-specific.

That installation strategy belongs to the selected provider adapter, because different backends such as Codex, Claude Code, or Gemini CLI may require different runtime-home layouts or sync behavior.

Visible runtime skill ids are plain workspace skill ids, for example `maverick-code-skill` or `chat-ops`. They are intentionally not namespaced by core or source app. The selected `skill.catalog` provider owns the editable runtime catalog for that session and must prevent or resolve name collisions before saving a skill.

The workspace app named `Skills` is the canonical built-in operator view for runtime skills.

It owns editable workspace skills under `workspaces/<workspace_id>/data/skills/skills/`.

It does not discover `~/.codex/skills`, plugin skills, system skills, or any other host Codex skill directories.

Bundled product skill templates may live under app source directories such as `apps/skills/skills/` and `apps/chat/skills/`, but runtime agents never read those source paths directly. Install and migration hooks copy missing templates into workspace data, and all subsequent edits happen on the workspace copy.

## Naming Conventions

The new core should use naming that keeps the file tree readable.

### Folder naming

Use short singular domain names:

- `identity/`
- `workspaces/`
- `apps/`
- `runtime/`
- `inter_agent/`
- `providers/`
- `execution_policy/`
- `secrets/`
- `recovery/`
- `observability/`
- `mcp/`
- `cli/`
- `skills/`

Avoid vague folders such as:

- `platform/`
- `support/`
- `utils/`
- `misc/`

unless the contents are truly cross-cutting and cannot belong to a domain.

### File naming

Prefer noun or action-specific filenames over overloaded generic names.

Good examples:

- `service.py`
- `routes.py`
- `models.py`
- `store.py`
- `policy.py`
- `runtime_session.py`
- `runtime_turns.py`
- `runtime_events.py`
- `delegation_service.py`
- `message_delivery.py`
- `provider_registry.py`
- `provider_openai.py`
- `provider_anthropic.py`
- `secret_bindings.py`
- `workspace_limits.py`
- `runtime_cli.py`
- `providers_cli.py`
- `recovery_cli.py`

Avoid names like:

- `helpers.py`
- `common.py`
- `manager.py`
- `base.py`

unless the file is truly the canonical implementation of that concept.

### Size rule

Files should stay small enough that one file usually contains one responsibility.

As a practical rule:

- if a file starts mixing routes, persistence, domain logic, and serialization, split it
- if a file has multiple unrelated public entrypoints, split it
- if a filename stops explaining the contents clearly, split it

### Recommended per-domain file pattern

Not every domain needs every file, but this should be the default pattern:

```text
<domain>/
  routes.py
  service.py
  models.py
  store.py
  errors.py
```

When a domain grows, split further by concept instead of creating monoliths:

```text
runtime/
  runtime_session.py
  runtime_turns.py
  runtime_events.py
  runtime_process.py
  routes.py
```

```text
inter_agent/
  delegation_service.py
  message_delivery.py
  delivery_reconcile.py
  models.py
  routes.py
```

```text
providers/
  provider_registry.py
  provider_models.py
  provider_credentials.py
  provider_openai.py
  provider_anthropic.py
  provider_codex.py
  provider_local.py
```

```text
cli/
  workspace_cli.py
  apps_cli.py
  runtime_cli.py
  inter_agent_cli.py
  providers_cli.py
  recovery_cli.py
```

```text
skills/
  runtime-orchestration/
    SKILL.md
  inter-agent-operations/
    SKILL.md
  provider-configuration/
    SKILL.md
```

## Illustrative File Layout

The target folder structure should move toward something like this:

```text
core/
  main.py
  api/
    application.py
    lifecycle.py
  identity/
    routes.py
    service.py
    models.py
    store.py
  workspaces/
    routes.py
    service.py
    models.py
    store.py
    governance.py
    limits.py
  apps/
    routes.py
    service.py
    models.py
    install_store.py
    lifecycle.py
    compatibility.py
  runtime/
    routes.py
    runtime_session.py
    runtime_turns.py
    runtime_events.py
    runtime_process.py
    runtime_state.py
  inter_agent/
    routes.py
    models.py
    delegation_service.py
    message_delivery.py
    delivery_queue.py
    delivery_reconcile.py
  providers/
    routes.py
    provider_registry.py
    provider_models.py
    provider_credentials.py
    provider_selection.py
    provider_codex.py
    provider_openai.py
    provider_anthropic.py
    provider_local.py
  execution_policy/
    policy.py
    sandbox_policy.py
    full_access_policy.py
    workspace_boundary.py
  secrets/
    models.py
    errors.py
    store.py
    routes.py
    secret_store.py
    secret_bindings.py
    secret_resolution.py
    service.py
  recovery/
    models.py
    errors.py
    store.py
    routes.py
    runtime_recovery.py
    failed_start_recovery.py
    health_checks.py
    service.py
  observability/
    models.py
    errors.py
    store.py
    event_log.py
    audit_log.py
    runtime_log.py
    metrics.py
    service.py
  mcp/
    server.py
    tool_registry.py
    platform_tools.py
  cli/
    workspace_cli.py
    apps_cli.py
    runtime_cli.py
    inter_agent_cli.py
    providers_cli.py
    recovery_cli.py
  skills/
    runtime-orchestration/
      SKILL.md
    inter-agent-operations/
      SKILL.md
    provider-configuration/
      SKILL.md
  shared/
```

This tree is intentionally explicit.

It is better to have more files with obvious names than fewer files with mixed responsibilities.

## Database Ownership In The Core

The core database should remain limited to platform-level records such as:

- users
- auth sessions
- workspaces
- workspace memberships
- app installation metadata
- runtime operational state
- secret metadata
- audit and platform logs
- quotas and governance state

The core database should not become the default storage engine for app business data.

Password resets and user deactivation are auth-session lifecycle events. When a user's password credential changes or the user is deactivated, the core identity service must revoke that user's existing auth sessions. Request session resolution must also reject inactive users even if an old active session record still exists.

## Design Summary

The target Maverick core should be:

- headless
- standalone
- platform-scoped
- app-agnostic
- workspace-aware
- operationally safe

It should own:

- identity
- governance
- app hosting
- runtime orchestration
- inter-agent communication
- AI provider management
- orchestration
- execution policy
- secret management
- recovery
- MCP surface
- CLI surface
- workspace skill catalog resolution through the runtime session's selected `skill.catalog` provider

It should not own:

- app domain models
- app data schemas
- app business content
- workspace business content

This is the foundation required to rebuild the core in a clean and scalable way.
