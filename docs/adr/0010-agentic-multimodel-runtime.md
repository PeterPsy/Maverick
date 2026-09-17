# ADR 0010: Direct Agentic Multi-Model Configuration

- Status: Accepted
- Updated: 2026-09-17

## Context

Maverick supports native coding runtimes and hosted API models. A previous
design represented availability through immutable profile revisions, rollout
states, workspace lineage, signed/digested execution metadata, Full Workspace
contracts and compatibility migrations. That duplicated ordinary provider
configuration and could disable a working model because metadata diverged.

## Decision

Maverick stores one current `AgenticProfileDefinition` for each configured
runtime/provider/model and one direct workspace binding for each workspace
choice. The word “profile” remains a domain type name; it no longer implies a
release object, revision history or certification lifecycle.

The current definition contains only model execution settings: runtime and
adapter, provider/model/protocol, route, supported reasoning, capabilities,
policy, egress and context policy. The workspace binding adds enable/default,
credential reference, actor policy and any workspace policy narrowing.

Publishing a changed model updates its stable definition id in place. Core does
not create preview/available/suspended revisions. Chat and Settings display the
records returned by Core directly and do not group or hide historical rows.

## Runtime families

- **Native Agents** own their loop and tools; Maverick launches and supervises
  the installed structured runtime. Codex is the primary implementation.
- **Maverick Agents** use a hosted API while Core owns the action loop, tools,
  bounded context, accounting and recovery.
- **Text-only Models** use a separate no-tools hosted-text path.

Execution-family labels are derived presentation/routing information. They are
not persisted release state on an agentic definition or session binding.

## Session binding

At session creation Core resolves the enabled workspace config and stores a
small `RuntimeExecutionBinding` containing only:

- session/workspace/workspace-config ids;
- runtime and adapter id/version;
- provider, model, model policy, protocol and route;
- credential reference and selected reasoning;
- capability, execution-mode and runtime-policy snapshots;
- egress and context policy settings;
- creation time.

It does not store definition revisions, workspace-binding revisions, execution
families, launch recipes, provider catalog/config digests, adapter identity
digests or a self-digest.

## Live authorization

Before dispatch and effects, Core derives ephemeral `RuntimeAuthority` from the
session inputs and current state. It checks the enabled workspace config, actor,
credential, health, execution mode, feature flags, tool permissions, route and
egress. Live state may narrow a session but cannot broaden it.

These checks are ordinary runtime authorization. They do not certify a model,
have no renewal schedule and are not persisted as a model-availability object.

## Model discovery

Native catalog discovery has no expiry gate. A successful refresh updates the
catalog; a failed refresh retains the last usable snapshot. Hosted endpoints use
their explicitly configured route and do not require a mutable vendor-catalog
status to approve every request.

## Recovery

An executable session runs directly. An incompatible stored session returns
`runtime_session_restart_required`; users start a new conversation. Core does
not auto-fork continuation sessions, maintain lineage admission, or rewrite old
bindings during backend bootstrap.

## Persistence and retention

Bootstrap reads only the current schema and performs no agentic compatibility
migration. Obsolete control-plane revisions are compacted once outside backend
startup. Historical runtime events and transcripts remain inert audit/user data
until their owning session or thread is deleted; they never grant authority.
Inactive recovery backups are not retained. User-created Storage documents stay
under normal Storage retention.

## Consequences

- Adding or updating a model changes one current config.
- Composer rows correspond to real current workspace choices.
- Transient discovery failures do not expire Codex.
- Credentials, health, sandbox/full access, tool permissions and egress remain
  enforced without a parallel certification system.
- Incompatible old sessions fail explicitly instead of triggering hidden
  migrations or continuation machinery.
