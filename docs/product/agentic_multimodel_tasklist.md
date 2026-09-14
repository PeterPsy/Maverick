# Agentic Multi-Model Runtime — Delivery and Development Plan

Updated: 2026-09-14

## Product objective

Provide OpenRouter `z-ai/glm-5.3-flash` as a Full Workspace agent driven by the
Maverick tool loop, with a user experience comparable to the native Codex path.
Codex must remain independently usable throughout OpenRouter changes. Google API
integration is not part of the current delivery objective.

## Delivered runtime

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
- [x] Native Codex app-server catalog projection.
- [x] Separate text-only provider path with no actions.

## Profile management

- Profile definitions are immutable and revisioned.
- Rollout state determines whether a profile can be selected.
- A workspace binding determines enablement, credential reference, actor/policy
  narrowing and the default selection.
- Core computes live effective authority from the direct profile plus current
  workspace, provider, runtime, model, credential, egress and tool state.
- Model or adapter updates create/reconcile the current profile revision for new
  sessions; existing sessions retain their immutable binding.
- Administration surfaces may expose revision history. Chat and Settings show
  one entry per execution family/provider/model, preferring the configured
  default and otherwise the newest eligible revision.

## Security boundaries

- [x] Authentication and workspace authorization.
- [x] Core secret/provider credential bindings.
- [x] Runtime sandbox/full-access policy.
- [x] Remote data classification and egress policy.
- [x] Containment and feature flags.
- [x] Reviewed Core tool schemas and dynamic wrapper revalidation.
- [x] Effect classification and confirmation.
- [x] Request/tool journals, budgets, cancellation and recovery.
- [x] Public/private payload separation and redaction.

## Acceptance completed

- [x] Backend restarted on the direct persistence/API shape.
- [x] Health and provider projections verified after restart.
- [x] Existing OpenRouter secret binding detected without exposing its value.
- [x] OpenRouter GLM selectable in the target workspace.
- [x] Real bounded OpenRouter agentic turn completed with a governed tool call.
- [x] Codex remained selectable and started a normal native session.
- [x] Composer groups repeated historical revisions into one model entry.
- [x] Persisted session pins and completed handoffs use the current direct
  binding schema.
- [x] Focused Python, Chat and Settings suites pass.
- [x] Fast functional areas pass apart from independently documented repository
  convention baselines.

## Ongoing development plan

- [ ] Keep a focused composer regression for repeated profile revisions and
  default-binding priority.
- [ ] Run an OpenRouter GLM agentic smoke after adapter, routing, tool-loop or
  effective-authority changes.
- [ ] Run an independent Codex start/turn smoke after provider catalog changes.
- [ ] Extend governed-tool integration coverage as new Full Workspace actions
  are added.
- [ ] Improve operator diagnostics for credential, route, upstream and policy
  failures without exposing secrets or provider-private state.
- [ ] Keep Chat, Settings and `/api/providers` selection semantics aligned.

## Validation record

The 2026-09-14 live validation used the enabled direct OpenRouter binding in
workspace `default` with `max` reasoning and Full Workspace mode. Session
`b034ef59-d443-4bc2-b8c5-807ebadd0ec8` completed in two provider steps after a
governed `core-capability:filesystem.list` call. The proposed, started and
completed tool events were persisted, the expected final marker was returned,
usage was recorded and no runtime error occurred.

Codex remained installed, healthy and selectable after the same backend
restart. Prepared session `ceb73c4b-b3c4-4f0c-902d-acaa57bba00d` started in
Full Workspace mode with provider `codex`.

The complete Python unit discovery passed 1,207 tests with five skips. The Chat
and Settings focused frontend suites and builds passed. The fast suite passed
all functional areas; its four failures were pre-existing repository convention
checks for file size/layout/reference budgets. One unrelated temporary-directory
cleanup race in the Chat/Codex project-delete test passed immediately when rerun
in isolation.

The active JSON control plane stores direct profile capability and reasoning
fields. Workspace bindings and immutable session pins preserve selection state,
while live runtime checks can only narrow what a profile declares.

The persistence migration normalized 96 session bindings and 16 completed
continuation handoffs to that direct schema. One already-invalid historical
binding was closed as failed while preserving its transcript; strict hydration
then succeeded for all 101 persisted sessions and all 16 handoffs.
