# Agentic Provider Activation Runbook

This runbook activates a direct agentic profile for new sessions. It does not
create model authority; the profile already declares the runtime contract.

## Scope

The primary hosted target is OpenRouter GLM 5.3 Flash using the Maverick-owned
agent loop. Google API activation is outside this runbook.

## Preconditions

1. The backend is running the current source and reports healthy.
2. The OpenRouter provider definition is active.
3. A Core secret and provider credential binding exist for the workspace.
4. `agentic-profile-openrouter-glm-5-3-flash-relace@1` is published with rollout
   `available`.
5. The workspace binding is enabled and its policy retains Full Workspace.
6. The workspace data/egress policy permits the intended data classes.
7. Provider and global hosted-agent feature flags are enabled.

Do not expose or copy the OpenRouter key into shell output, app storage, browser
state, logs or runtime events.

## Read-only verification

Inspect provider status and confirm:

- execution family is `maverick_agent`;
- model is `z-ai/glm-5.3-flash`;
- Full Workspace status is `available`;
- profile and workspace binding are enabled;
- credential binding is present;
- containment is `GO`;
- live effective capabilities are `active`;
- reasoning efforts are `max`, `high`, `low`;
- endpoint/upstream and data destination match the profile.

A browser field is never sufficient evidence of authority. The server-owned
`selectable` and effective-capability projection are decisive.

## Activation

Use the provider administration API/CLI to create or update the workspace
binding with compare-and-set revision. Enable it for new sessions. Make it the
workspace default only when explicitly intended; activation and default
selection are separate operations.

Never rewrite existing runtime session bindings. New chats pin the current
direct profile. Existing chats retain their immutable session pin and pass live
policy checks on each turn.

## Smoke test

Create a new session selecting the OpenRouter workspace profile and `max`
reasoning. Run a bounded task that requires:

1. streamed assistant output;
2. filesystem list/read;
3. one write through the governed tool boundary;
4. one CLI or MCP invocation;
5. final answer and usage persistence.

Verify that the session execution binding contains direct capability and
reasoning snapshots, provider/model/route identity and no secret material.
Verify that public events contain no raw provider-private history.

## Failure handling

Stop activation if any of these occur:

- authentication failure or missing credential binding;
- unexpected endpoint, model or upstream;
- containment `NO-GO`;
- Full Workspace/profile family incomplete;
- effective authority blocked;
- request/tool journal mismatch;
- unclassified or unauthorized tool effect;
- leaked secret, host path or provider-private payload;
- cancellation/recovery cannot reach a deterministic terminal state.

Disable the workspace binding or provider feature flag to stop new work. Do not
repair an outage by changing dates or issuing another capability artifact; fix
the profile, adapter, provider config, credentials or live policy that actually
failed.

## Codex stability

OpenRouter changes must not restart Codex, rewrite Codex bindings or alter Codex
session history. Codex model/catalog changes follow normal profile reconciliation
and do not require a Maverick renewal step.
