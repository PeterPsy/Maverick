# ADR 0010: Direct Agentic Multi-Model Runtime Profiles

- Status: Accepted
- Updated: 2026-09-14

## Context

Maverick supports agentic work through both native coding runtimes and hosted
model APIs. The platform needs one stable contract for model selection,
capabilities, policy, routing, recovery and workspace tools without coupling
availability to a second Maverick-issued lifecycle.

A previous design copied profile capabilities into separately issued, expiring
records. That duplicated provider/model identity, introduced renewal and
revocation workflows, made ordinary Codex updates capable of disabling the
runtime, and added no authority that could not be derived from the profile and
live platform policy.

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

There is no additional Maverick issuance, renewal, expiry or reactivation step.
A profile is usable when its rollout, workspace binding, runtime/provider state
and live policy checks allow it.

## Execution families

### Native Agents

Native agents own their own loop and tools. Maverick launches and supervises a
structured runtime, validates its installation and live model catalog, confines
its effects, and projects it into the common session/runtime contract. Codex is
the primary implementation and uses app-server rather than one-shot commands.

A new model advertised by the current Codex catalog receives a normal
model-bound profile projection. A Codex source or package update does not require
Maverick to renew a separate artifact and cannot disable the runtime merely
because source bytes changed.

### Maverick Agents

Maverick Agents use a hosted inference API while Core owns the action loop,
tools, confirmations, context, provider-private continuation state, budgets,
finalization and recovery. Protocol adapters remain provider codecs/transports;
they do not become policy authorities.

The OpenRouter implementation targets `z-ai/glm-5.3-flash` through the Relace
route and the `openrouter-chat-completions` adapter. It declares the Full
Workspace capability surface and reasoning efforts `max`, `high`, and `low`.

### Text-only Models

Text-only API models have no workspace tools or action loop. A session pins a
`HostedTextExecutionBinding` with provider/model profile, availability and
routing. Text-only bindings are never accepted by the agentic loop.

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

The result is ephemeral, non-bearer and can only narrow the session pin. Browser
payloads cannot add capabilities, classify data or supply provider authority.

## Tool safety

Provider admission and tool-schema safety are separate concerns. Hosted models
receive only Core-owned base tool schemas marked as reviewed. Dynamic app/CLI/MCP
tools are discovered and invoked through bounded Core wrappers that re-resolve
live app bindings, actor policy, execution mode, effects and output policy.

The reviewed-schema marker has no model admission, renewal or expiry semantics.
It only distinguishes Core-owned schema projections from untrusted dynamic
schema input.

## OpenRouter routing and state

The OpenRouter profile pins its endpoint, model identity, allowed upstream,
fallback policy, parameters and provider config. Core resolves the API key from
its secret binding and never persists or returns it.

Core validates the exact request envelope but does not perform a separate live
vendor-catalog probe before each completion step. The vendor catalog is useful
for operator discovery, not runtime bearer authority: mutable or undocumented
catalog status values cannot veto a request that the configured OpenRouter
endpoint can serve. OpenRouter enforces the requested route, parameter and ZDR
constraints, and the adapter validates the actual streamed provider/model
identity before accepting output.

The adapter supports streamed text and tool calls, bounded provider-private
history, call/result pairing, cancellation, normalized errors, token accounting,
finalization and recovery. Each request revalidates live authority before
network egress and before each tool effect.

## Persistence and compatibility

Current control-plane persistence contains profiles, rollout status, workspace
bindings, provider definitions/selections and credential references. Runtime
sessions persist direct execution bindings and provider-private state.

Legacy stored keys from the retired issued-capability design are ignored during
hydration. They grant no authority and the direct binding digest is recomputed.
No new API, CLI, MCP or storage collection exposes that retired lifecycle.

Historical session bindings remain immutable. Compatible continuation may fork
a child session after a non-expansion proof; incompatible state requires a new
conversation or explicit transcript handoff.

## User interfaces

`GET /api/providers` and the administration projection expose direct profile
capabilities, Full Workspace availability, reasoning, routing, containment,
live preflight and effective authority. Chat and Settings use the server's
`selectable`/`enable_eligible` results and do not derive authority locally.

No expiry warning, renewal control or issued-status badge is shown. The compact
Chat selector shows model, provider and reasoning. Settings shows profile,
routing, binding, policy, health and effective capabilities.

## Security properties retained

This decision removes duplicated admission state, not security enforcement.
Authentication, authorization, credentials, containment, sandboxing, egress,
data classification, approvals, tool effect review, output classification,
budgets, cancellation and live policy revalidation remain mandatory.

## Consequences

- Codex and OpenRouter availability no longer depends on time-based renewal.
- Adding or updating models uses normal profile/catalog evolution.
- API and UI contracts are smaller and have one capability source of truth.
- Operational testing remains valuable, but test reports do not become runtime
  bearer authority.
- A profile bug is fixed in code/profile data and validated by tests rather than
  repaired by extending an expiry date.
