# Runtime Provider Model

This reference describes the current provider and agentic runtime contract.

## Provider roles

- `runtime_engine`: owns an agent runtime/loop, for example Codex.
- `model_provider`: exposes a hosted inference API, for example OpenRouter.
- `speech_provider`: exposes speech-specific operations.

Provider credentials are Core secrets referenced by logical bindings. Provider
and workspace APIs return only redaction-safe binding metadata.

## Execution families

| Family | Loop owner | Workspace actions |
| --- | --- | --- |
| `native_agent` | Native structured runtime | Yes, under Maverick supervision |
| `maverick_agent` | Maverick Core | Yes, through Core tools |
| `hosted_text` | None | No |

The provider status API returns these in the product order Native Agents,
Maverick Agents, then Text-only Models.

## Agentic profile

An `AgenticProfileDefinition` is immutable and directly declares:

- engine, adapter, provider, model and protocol identity;
- exact or alias model revision policy;
- routing constraint and allowed upstreams;
- reasoning efforts/default;
- capability set and policy ceiling;
- egress policy;
- execution family, Full Workspace revision and harness recipe;
- provider config and protocol-adapter identity;
- context/tool contract revisions.

A separate rollout status controls whether a definition is preview, available,
suspended or disabled. A workspace binding selects one definition, optional
credential reference, actor policy, policy narrowing and default status.

Maverick does not maintain a second issued or expiring capability lifecycle.
Profile capabilities are the sole declared capability source.

## Direct capabilities

`RuntimeCapabilitySet` covers streaming, tool orchestration, CLI, MCP, skills,
filesystem list/read/write, shell, interrupt, steering, recovery, confirmation
resume, provider-private state, attachment modalities, app references and
confirmations.

Capabilities do not grant themselves. Live authority always intersects them
with policy and current authorization.

## Session pin

A `RuntimeExecutionBinding` pins:

- definition/binding ids and revisions;
- runtime adapter identity;
- provider/model/revision/protocol;
- selected reasoning and allowed reasoning tuple;
- direct capability snapshot;
- routing, provider config and protocol adapter;
- profile/workspace policy ceilings and egress revision;
- family, Full Workspace and harness identities;
- context/tool contract identities.

The binding is self-digesting. Client data cannot create or modify it. Legacy
retired fields are discarded during hydration and never grant authority.

## Effective authority

For every turn Core computes `EffectiveRuntimeAuthority` from the session pin and
live state. It validates workspace binding, actor policy, execution mode, feature
flags, health, credentials, model availability, upstream restrictions, egress,
remote-data policy and current tool handles. The result can only remove
capabilities.

Public capability snapshots include the effective capability set, execution
mode, provider/model/routing health, data policy, Full Workspace/recipe metadata
and policy revisions. They contain no secret or bearer authority.

## Codex

Codex is a `native_agent` using the `codex-app-server` adapter. Its current model
catalog and reasoning metadata are discovered from the configured Codex runtime.
Each model gets a content-addressed model profile projection.

A new catalog slug or ordinary Codex update does not require a Maverick renewal.
Availability depends on the live installation/catalog, the direct profile,
workspace binding and normal policy checks. Persisted model metadata does not
override the current built-in/live catalog.

Codex sessions use a sanitized runtime-specific home. Global connectors and
unapproved inherited configuration are removed. Runtime processes are supervised
and continuation preserves the provider conversation under Core ownership.

## OpenRouter GLM agent

The built-in Full Workspace profile is:

- profile: `agentic-profile-openrouter-glm-5-3-flash-relace@1`;
- execution family: `maverick_agent`;
- runtime engine: `maverick-tool-loop`;
- model provider: `openrouter`;
- model: `z-ai/glm-5.3-flash`;
- resolved catalog model: `z-ai/glm-5.3-flash-20260826`;
- protocol: `openrouter-chat-completions@v1`;
- endpoint: `https://openrouter.ai/api/v1/chat/completions`;
- upstream: `relace`, with profile-defined fallback policy;
- reasoning: `max` (default), `high`, `low`.

The direct capability profile includes streaming, Core tool orchestration,
CLI/MCP, skills, filesystem operations, shell, interrupt, recovery,
provider-private state, app references and confirmations.

The Core-owned loop:

1. resolves live authority;
2. materializes bounded governed context and reviewed base tool schemas;
3. submits a streamed OpenRouter request using the Core secret binding;
4. normalizes text/tool deltas and private state;
5. validates and executes tool calls through the official tool boundary;
6. appends paired tool results and repeats within policy budgets;
7. finalizes output/usage and persists only bounded public events plus encrypted
   provider-private continuation state.

Selecting the profile requires an active OpenRouter provider/credential binding,
an enabled workspace profile, Full Workspace readiness, a `GO` containment state
and active live effective authority.

## Hosted text

A text-only session pins `HostedTextProfileDefinition`, status and provider route
inside `HostedTextExecutionBinding`. It explicitly presents `No workspace tools
or actions.` Every request revalidates provider/model/endpoint/modalities/limits,
cost, retention, destination and routing. Drift fails closed instead of silently
routing elsewhere.

## Tool contract

Core-owned static tool schemas may carry `reviewed_schema_component` with the
fixed reviewed catalog id. Dynamic CLI/MCP/app tools are not copied into base
provider requests. They are exposed through discovery/invocation wrappers with
live actor, workspace, app-binding, effect and output checks.

Tool review is independent of model/profile admission and has no time-based
lifecycle.

## Fail-closed conditions

New agentic sessions are rejected when any required binding, credential, actor,
model, runtime, route, feature, Full Workspace contract or containment check is
not available. Existing sessions revalidate mutable authority before network
submission and side effects.

Provider errors are normalized to stable reason codes. Raw upstream payloads,
credentials, host paths and provider-private messages are not exposed in public
runtime events.
