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
- [x] Direct OpenRouter dispatch without a mutable per-step catalog veto.
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

- [x] Backend restarted on the new persistence/API shape.
- [x] Health and provider projections verified after restart.
- [x] Existing OpenRouter secret binding detected without exposing its value.
- [x] OpenRouter GLM selectable in the target workspace.
- [x] Real bounded OpenRouter agentic turn completes with a governed tool call.
- [x] Codex remains selectable and can start a normal native session.
- [x] Focused Python, Chat and Settings suites pass.
- [x] Fast suite passes except independently documented repository-baseline
  convention failures.

## Validation record

The 2026-09-14 live validation used the enabled direct OpenRouter binding in
workspace `default` with `max` reasoning and Full Workspace mode. Session
`b034ef59-d443-4bc2-b8c5-807ebadd0ec8` completed in two provider steps after a
governed `core-capability:filesystem.list` call. The proposed, started and
completed tool events were persisted, the expected final marker was returned,
usage was recorded and no runtime error occurred.

Codex remained installed, healthy and selectable after the same backend
restart. Prepared session `ceb73c4b-b3c4-4f0c-902d-acaa57bba00d` started in
Full Workspace mode with provider `codex` and no issued-capability fields.

The complete Python unit discovery passed 1,202 tests with five skips. The Chat
and Settings focused frontend suites and builds passed. The fast suite passed
all functional areas; its four failures are the pre-existing repository
convention checks for file size/layout/reference budgets. One unrelated
temporary-directory cleanup race in the Chat/Codex project-delete test passed
immediately when rerun in isolation.

The active JSON control plane was upgraded in place: all profile definitions
now carry direct capability and reasoning fields, the three retired issued
capability collections are absent, and the obsolete private signing secret and
encrypted value were removed. Historical session records remain immutable and
their ignored legacy metadata grants no authority.
