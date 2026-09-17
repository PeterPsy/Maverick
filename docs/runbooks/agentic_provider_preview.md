# OpenRouter GLM Agent Activation Runbook

This runbook activates the current OpenRouter GLM config for new sessions.

## Preconditions

1. The backend is healthy and running the current source.
2. OpenRouter is active and the workspace has a Core-managed credential binding.
3. The direct `z-ai/glm-5.3-flash` workspace config is enabled.
4. Hosted-agent feature flags, workspace execution policy and egress policy
   permit the intended session.

Never expose the API key in shell output, workspace files, browser state, logs
or runtime events.

## Read-only verification

Inspect provider status and confirm:

- family `maverick_agent`, runtime `maverick-tool-loop`;
- model `z-ai/glm-5.3-flash` and reasoning `max`, `high`, `low`;
- expected endpoint, Relace upstream and data destination;
- enabled workspace config and credential binding;
- healthy runtime, `GO` containment and active effective capabilities.

These are direct runtime checks. There is no rollout revision, Full Workspace
contract, harness digest or catalog certificate to renew.

## Activation

Use the provider administration surface to create or update the direct workspace
binding. Enable it for new sessions and set it as default only when explicitly
intended. A changed model or route updates the stable current config in place;
it does not publish a new revision.

Existing sessions keep their concrete execution inputs. If those inputs become
incompatible, the session reports `runtime_session_restart_required` and the
user starts a new conversation.

## Smoke test

Create a new OpenRouter session with `max` reasoning and run a bounded task that
requires streamed output, filesystem read, one governed write and one CLI or MCP
call. Verify final output and usage persistence, and verify that no credential or
provider-private history appears in public events.

## Failure handling

Stop activation for an authentication failure, unexpected route/upstream,
unhealthy runtime, containment `NO-GO`, blocked tool/egress policy, leaked
private data or non-terminal cancellation. Disable the workspace config to stop
new work, correct the real dependency or policy, and repeat verification.

OpenRouter changes must not rewrite Codex config or session history. Codex
discovery retains its last usable catalog when a refresh fails.
