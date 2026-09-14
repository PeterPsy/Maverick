# Agentic Multi-Model Runtime — Delivery and Development Plan

Updated: 2026-09-14

## Product objective

Provide OpenRouter `z-ai/glm-5.3-flash` as a Full Workspace agent driven by the
Maverick tool loop, with a user experience comparable to the native Codex path.
Codex must remain independently usable throughout OpenRouter changes. New Google
endpoint onboarding is not part of this delivery, but the existing Google
hosted adapter follows the same universal loop and full-access contract.

## Delivered runtime

- [x] Native Agent and Maverick Agent execution families.
- [x] Direct immutable profile capabilities and reasoning choices.
- [x] Self-digesting session execution bindings.
- [x] Live profile/workspace/actor/credential/health/egress authority
  intersection.
- [x] Core-owned hosted tool loop with streaming, confirmations, recovery and
  provider-private state.
- [x] Provider-neutral tool loop with concurrent execution and independent
  result/error pairing for multi-call batches.
- [x] Complete authorized tool catalog retained across model steps, without a
  runtime-directed tool-less finalization phase.
- [x] Shared relative/workspace-URI/absolute path normalization for filesystem,
  shell and managed-process tools.
- [x] Direct full-access host filesystem, process and installed-CLI execution;
  sandbox confinement remains available for narrower profiles.
- [x] Full-access egress/classification audit without payload transformation or
  content filtering.
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
- [x] Enforced sandbox egress policy and audit-only full-access egress policy.
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
- [x] Run an OpenRouter GLM agentic smoke after adapter, routing, tool-loop or
  effective-authority changes.
- [x] Run an independent Codex start/turn smoke after provider catalog changes.
- [ ] Extend governed-tool integration coverage as new Full Workspace actions
  are added.
- [ ] Improve operator diagnostics for credential, route, upstream and policy
  failures without exposing secrets or provider-private state.
- [ ] Keep Chat, Settings and `/api/providers` selection semantics aligned.
- [ ] Keep the Codex/OpenRouter parity matrix current for filesystem,
  shell/CLI, parallel reads, managed processes, writes, MCP/skills, restart and
  self-correction after a tool error.

## Review hardening

- [x] Replace the ambiguous zero parallelism value with an explicit
  `unbounded` contract while accepting legacy session pins.
- [x] Keep provider/upstream routing enforcement active in audit-only mode.
- [x] Enforce aggregate result bytes in the actual provider payload and persist
  restart-stable omitted-result identities.
- [x] Extract the concurrent batch executor from the hosted loop and cover
  sibling failure plus cancellation.
- [x] Stream full-access list/search scans with entry/read limits,
  cancellation checks and page-entry classification joins.
- [x] Restore the bounded turn-side prewarm delay/join; only the client-facing
  prepare call remains non-blocking, with no unmeasured cold-start claim.
- [x] Bind hosted full-access runtime bearers to one live turn and revoke them
  on every terminal turn transition; keep native process tokens intentionally
  session-scoped.
- [x] Extract a bounded filesystem scanner with deterministic per-directory
  ordering and multipage cursor coverage.
- [x] Cover an interrupted OpenRouter tool step with a fresh adapter instance,
  same-turn journal recovery and no repeated tool effect.
- [x] Record the final post-commit OpenRouter GLM and Codex restart smoke below.

## Validation record

Current 2026-09-14 validation passes 1,227 root unit tests with five skips, 381
provider tests, 204 runtime-state tests, 171 runtime-tool tests, 28 egress tests
and 350 API tests. The complete fast run passes every functional area and app
shard; its only non-zero checks are the three existing repository convention
baselines for file-size/layout/reference budgets.

The controlled in-flight recovery test interrupts the OpenRouter loop after a
filesystem result and provider step are durably committed, constructs a fresh
adapter over the same store, reconciles the journal and completes the original
turn. The second provider request contains the persisted result and the tool
ledger contains one invocation, proving that recovery does not repeat the
effect. This test also protects current and persisted compatible budget journal
schemas.

The live parity smoke used OpenRouter session
`b2eae95d-a5e4-42d4-b401-c6404e258353` for concurrent filesystem reads and a
shell call containing `git`, `rg` and authenticated `maverick` CLI execution.
The same session accepted a new tool turn after restart. Codex session
`b1610ebb-6a15-4ed9-a328-709babcf22f2` likewise completed filesystem and CLI
work before restart and a new tool turn afterwards. These live checks establish
persisted-session continuity; the controlled fault test above establishes
in-flight same-turn recovery.

Historical counts of 1,207, 1,214 and 1,223 tests were intermediate delivery
snapshots and are superseded by the current result above. The direct control
plane migration normalized 96 session bindings and 16 completed continuation
handoffs; strict hydration then succeeded for all persisted sessions and
handoffs while preserving the transcript of one already-invalid binding closed
as failed.
