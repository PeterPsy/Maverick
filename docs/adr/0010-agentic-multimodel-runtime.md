# ADR 0010: Direct Agentic Multi-Model Runtime Profiles

- Status: Accepted
- Updated: 2026-09-14

## Context

Maverick supports agentic work through native coding runtimes and hosted model
APIs. The platform needs one stable contract for model selection, capabilities,
policy, routing, recovery and workspace tools. The contract must remain simple
enough that adding a model or updating Codex follows the normal provider and
profile workflow.

## Decision

Maverick uses direct, immutable agentic profiles.

`AgenticProfileDefinition` owns the complete runtime declaration:

- runtime engine and adapter identity;
- model provider, model and revision policy;
- provider protocol and API version;
- routing and upstream constraints;
- reasoning efforts and default effort;
- `RuntimeCapabilitySet`;
- profile policy ceiling and egress policy;
- execution family and Full Workspace revision;
- harness recipe, provider config and protocol-adapter identity.

A profile is usable when its rollout, workspace binding, runtime/provider state
and live policy checks allow it. Model availability has no separate admission
object or time-based gate.

## Execution families

### Native Agents

Native agents own their own loop and tools. Maverick launches and supervises a
structured runtime, validates its installation and live model catalog, confines
its effects, and projects it into the common session/runtime contract. Codex is
the primary implementation and uses app-server rather than one-shot commands.

Each model advertised by the current Codex catalog receives a normal model-bound
profile projection. A Codex source, package or catalog update reconciles those
profiles from the current runtime state. Existing sessions keep their immutable
pin; new sessions use the current selectable profile.

### Maverick Agents

Maverick Agents use a hosted inference API while Core owns one universal action
loop, tools, context, provider-private continuation state, resource accounting
and recovery. Protocol adapters translate request, stream and tool-call
protocols; they do not direct model behavior or become policy authorities.

Every authorized tool remains in the catalog for every new-turn step. A batch
of tool calls is executed concurrently with independent success/error pairing.
Core does not force sequencing, close the catalog, or reserve a tool-less final
step. Persisted legacy finalization records are supported only as a bounded
restart-recovery case.

The OpenRouter implementation targets `z-ai/glm-5.3-flash` through the Relace
route and the `openrouter-chat-completions` adapter. It declares the Full
Workspace capability surface and reasoning efforts `max`, `high`, and `low`.

### Text-only Models

Text-only API models have no workspace tools or action loop. A session pins a
`HostedTextExecutionBinding` with provider/model profile, availability and
routing. Text-only bindings are never accepted by the agentic loop.

## Profile and binding management

Definitions are immutable and revisioned. Rollout state controls whether a
definition is preview, available, suspended or disabled. A workspace binding
chooses the definition, optional credential reference, actor policy, policy
narrowing and default status.

When a model, adapter or contract changes, Core publishes or reconciles a new
profile revision. New chats resolve the current selectable binding. Existing
chats retain the binding captured at session creation and continue only while
live authority remains valid. Administration APIs may expose profile history;
product selectors group it by execution family, model provider and model, then
show the configured default or the newest eligible revision.

## Session authority

At creation, Core resolves an enabled `WorkspaceAgenticProfileBinding` and
builds a self-digesting `RuntimeExecutionBinding`. The binding pins the profile's
capabilities, reasoning, route, policy, model, adapter, recipe and provider
configuration for that session.

Before provider dispatch and effects, `EffectiveRuntimeAuthority` intersects the
pinned profile with:

- current workspace binding and actor policy;
- execution mode and feature flags;
- credential availability;
- provider/native runtime health;
- current model catalog and upstream constraints;
- egress and remote-data policy;
- currently authorized tool handles.

The result is ephemeral and non-bearer. Browser payloads cannot add
capabilities, classify data or supply provider authority. An explicit
full-access profile authorizes the complete runtime catalog; narrower profiles
continue to intersect it with their declared tool and effect policy.

## Tool safety

Provider admission and tool-schema safety are separate concerns. Hosted models
receive only Core-owned base tool schemas marked as reviewed. Dynamic app/CLI/MCP
tools are discovered and invoked through bounded Core wrappers that re-resolve
live app bindings, actor policy, execution mode, effects and output policy.

The reviewed-schema marker only distinguishes Core-owned schema projections from
untrusted dynamic schema input. It does not enable a provider or model.

Filesystem, shell and process tools use a shared path resolver. Sandbox mode
confines resolved paths and effects to the workspace. Full-access mode permits
relative, workspace-URI and absolute host paths, runs against the live host
filesystem/process environment, and exposes installed CLIs. Confirmations are
applied only when the selected profile explicitly requests them.

## OpenRouter routing and state

The OpenRouter profile pins its endpoint, model identity, allowed upstream,
fallback policy, parameters and provider config. Core resolves the API key from
its secret binding and never persists or returns it.

Core validates the exact request envelope but does not perform a separate live
vendor-catalog probe before each completion step. The vendor catalog is useful
for operator discovery, not runtime authority: mutable or undocumented catalog
status values cannot veto a request that the configured OpenRouter endpoint can
serve. OpenRouter enforces the requested route, parameter and ZDR constraints,
and the adapter validates the actual streamed provider/model identity before
accepting output.

The adapter supports streamed text and parallel tool-call batches, bounded
provider-private history, independent call/result pairing, cancellation,
normalized errors, token accounting and recovery. Each request refreshes live
authority before network egress and before each tool effect.

Parallelism is expressed as the explicit `unbounded` policy contract: every
call emitted in one provider step is independently executed, up to the existing
per-turn call budget. Provider-visible result bytes remain physically bounded;
an overflowing result is journaled as omitted and paired with a structured
error without cancelling its siblings.

## Persistence

Control-plane persistence contains profiles, rollout status, workspace bindings,
provider definitions/selections and credential references. Runtime sessions
persist direct execution bindings and provider-private state. Hydration accepts
the current binding schema and validates its digest before constructing runtime
authority.

Historical session bindings remain immutable. Compatible continuation may fork
a child session after a non-expansion proof; incompatible state requires a new
conversation or explicit transcript handoff.

## User interfaces

`GET /api/providers` and the administration projection expose direct profile
capabilities, Full Workspace availability, reasoning, routing, containment,
live preflight and effective authority. Chat and Settings use the server's
`selectable`/`enable_eligible` results and do not derive authority locally.

The compact Chat selector shows one entry per execution family, model provider
and model, plus its reasoning choices. Settings shows profile history, routing,
binding, policy, health and effective capabilities.

## Security properties

Authentication, authorization, credentials, execution-mode selection, resource
ceilings, cancellation and recovery remain Core responsibilities. Sandbox
profiles enforce containment, data classification, egress transformation and
configured approvals. In an explicit full-access profile, classification and
egress are audit/telemetry signals only: they do not redact, transform, compact
or veto content, and no confirmation is added unless that profile requests it.
Audit-only content handling still enforces the pinned destination provider and
upstream route; it cannot redirect exported bytes to an unselected transport.
Operational test reports are validation evidence, not runtime authority.

## Consequences

- Adding or updating models uses normal profile/catalog evolution.
- API and UI contracts have one declared capability source of truth.
- Codex availability follows its current installation, catalog, profile and live
  policy state.
- OpenRouter GLM and Codex expose the same operational Full Workspace
  capabilities even though their wire protocols and loop ownership differ.
- A profile bug is fixed in code/profile data and covered by tests.
