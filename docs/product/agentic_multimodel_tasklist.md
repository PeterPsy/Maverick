# Agentic Multi-Model Runtime — Current Delivery Checklist

Updated: 2026-09-14

## Delivered architecture

- [x] Native Agent and Maverick Agent execution families.
- [x] Direct immutable profile capabilities and reasoning choices.
- [x] Self-digesting session execution bindings.
- [x] Live profile/workspace/actor/credential/health/egress authority
  intersection.
- [x] Core-owned hosted tool loop with streaming, confirmations, recovery and
  provider-private state.
- [x] OpenRouter Chat Completions adapter for `z-ai/glm-5.3-flash`.
- [x] Full Workspace OpenRouter profile with `max`, `high`, `low` reasoning.
- [x] Codex native app-server catalog projection without a renewal dependency.
- [x] Chat and Settings selection based on direct server readiness.
- [x] Separate text-only provider path with no actions.

## Removed obsolete architecture

- [x] Separate issued capability records and status collections.
- [x] Expiry, renewal, revocation and evidence-publication workflows for model
  admission.
- [x] Provider-specific probe publication scripts that could change runtime
  authority.
- [x] Source-byte artifact guard that could disable Codex after an update.
- [x] Browser expiry/status badges and client eligibility filters.
- [x] API, CLI and MCP endpoints for the retired lifecycle.

## Security boundaries retained

- [x] Authentication and workspace authorization.
- [x] Core secret/provider credential bindings.
- [x] Runtime sandbox/full-access policy.
- [x] Remote data classification and egress policy.
- [x] Containment and feature flags.
- [x] Reviewed Core tool schemas and dynamic wrapper revalidation.
- [x] Effect classification and confirmation.
- [x] Request/tool journals, budgets, cancellation and recovery.
- [x] Public/private payload separation and redaction.

## Acceptance

- [ ] Backend restarted on the new persistence/API shape.
- [ ] Health and provider projections verified after restart.
- [ ] Existing OpenRouter secret binding detected without exposing its value.
- [ ] OpenRouter GLM selectable in the target workspace.
- [ ] Real bounded OpenRouter agentic turn completes with a governed tool call.
- [ ] Codex remains selectable and can start a normal native session.
- [ ] Focused Python, Chat and Settings suites pass.
- [ ] Fast suite passes except independently documented repository-baseline
  convention failures.
