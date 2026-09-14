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
- [x] Record the final post-commit OpenRouter GLM and Codex restart smoke below.

## Validation record

The universal-loop change was validated on 2026-09-14 with 378 provider tests,
190 runtime-state tests, 166 runtime-tool tests, and 27 egress tests passing.
The focused parity coverage exercises the shared Codex/OpenRouter capability
contract, live full-access list/read/search/write/edit/patch/move/delete,
installed `git`, `rg` and authenticated `maverick` CLI execution, managed
process start/status/stdin/interrupt, parallel Google and OpenRouter tool
calls, independent invalid-call recovery, and restart journal reconciliation.
The hosted runtime installs the same Maverick wrapper used by native runtimes,
adds installed vendored CLI paths without hard-coded package locations, and
uses a turn-scoped bearer so a CLI subcall is admitted during its owning
provider step while pending steps from another turn remain blocked.

The staged snapshot later committed as `12b1f61b` passed 1,223 root unit tests
with five skips. Focused suites passed 380 provider tests, 202 runtime-state
tests, 170 runtime-tool tests, 28 egress tests and 350 API tests. The fast suite
passed its unit, runtime, runtime-state, app-hosting, process, stream, script
and all app shards. Its only remaining failures are the three pre-existing
repository convention baselines for file-size/layout/reference budgets.

The final live OpenRouter sequence used session
`b2eae95d-a5e4-42d4-b401-c6404e258353`. Turn
`63d34bb6-9a9d-4824-976c-f6f985caa3a5` emitted two independent
`filesystem.read` calls in one provider response; both `started` events were
persisted before either `completed` event, and both results reached the final
answer. Turn `ed20d639-50a0-43c3-87ce-607972ae2689` then completed one
`shell.run` containing `git --version`, `rg --version` and
`maverick core cli list --json`, all at exit code zero. After a backend restart,
turn `737507c2-0f2b-418b-a3c7-7c58b25946c6` completed another filesystem tool
and final response in the same session.

After commit `12b1f61b` and a further backend restart, both persisted sessions
were healthy and continued normally. OpenRouter turn
`4f40aec8-00d4-4cf3-9dc1-6cdff2bae11f` completed a filesystem read and final
response. Codex session `b1610ebb-6a15-4ed9-a328-709babcf22f2`, which had
already completed two reads plus a shell turn containing the same three CLI
checks, completed post-restart turn `50c936a6-5906-4d06-abab-e905b19af803`
with another tool result and final response.

An isolated snapshot of the exact staged change passed all 1,214 root unit
tests with five skips. The fast suite also passed its API, runtime,
runtime-state, app-hosting, process, stream, script, and all 67 app shards. Its
remaining failures were the four pre-existing convention checks for accumulated
file-size/layout/reference budgets. A shared-working-tree run also observed one
continuation-fixture error from concurrent work that is excluded from this
commit. The one profile expectation exposed by this change was updated and
passes in the complete 378-test provider suite.

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
