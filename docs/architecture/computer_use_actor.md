# Internal computer-use operator

PC use retains one visible conversation and the user's selected planner model.
Every admitted native provider exposes `computer_interact` for bounded UI tasks.
The Core-owned operator uses a separate Codex provider context pinned explicitly
to `gpt-6-luna` / `low`; it is not a Chat thread or an inter-agent board participant.
Only read-only UI tools and structured project, code and calendar capabilities
remain directly available to the planner. Native UI input is brokered by Core
through the original activation/session/turn authority, never a copied Mac lease.

The operator has only native UI tools, an attested isolated credential home and
the existing process sandbox exposing only its private operator directory. The
parent workspace and runtime files are not mounted. It has disabled local
shell/filesystem/MCP/skills/web tools, and a bounded task card. It receives no full
chat transcript. Its process is reused while PC use is connected, and retired
with an idle/closed parent provider or the native lease. The owning controller
remains available to start a fresh process on the next authorized subtask.
Provider context is reset between bounded tasks so old screenshots, receipts and cumulative usage
cannot cross tasks. Its output and reasoning never become Chat messages. Normal
native operation evidence and aggregated usage remain on the owning conversation.
Its catalog omits companion-browser tools in bounded On mode. Actor instructions
retain native UI rules while omitting workspace, project and code guidance that
belongs to the planner. The parent tool lifecycle reports summed native timings
when every delegated operation supplies them.

The planner supplies objective, completion criterion, constraints and an explicit
`prepared_text` list of exact strings to enter. Core rejects actor text absent from
that list. The operator returns verified completion, a decision needed
or a blocker. It does not compose content or make business/creative decisions.
Ambiguous input cannot be replayed. Cancellation, parent-turn completion, lease
revocation, owner changes and user corrections fence further actor calls and stop
active inference. Actor failure does not transparently replay writes or silently
switch models/providers. Catalog availability is checked before launching.
Codex same-turn corrections also send the existing native turn-end control frame
to invalidate old observation receipts. Already dispatched operations remain
subject to native cancellation and outcome verification; Core never replays them.

Actor usage has an internal attribution scoped to the parent session and provider
thread. It contributes to delegated and total usage, while the main model's context
meter remains unchanged. Chat folds internal worker consumption into its ordinary
total without showing another model or delegation; diagnostics preserve the split.
Deleting the owning runtime also removes its private usage streams.
No new persisted control-plane schema or UI is introduced.
Tests cover protocol routing, image delivery, authority, bounded outputs, usage
stream isolation, cancellation and provider-independent tool projection. Performance
claims require a measured matched task; model choice alone is not a speedup result.

Implementation verification on 2026-10-08 includes 165 focused passing tests for
provider routing, private JSON-RPC, native lease/turn authority, steering, MCP,
reconnection, and usage in both document and SQLite stores. A live authenticated
Luna `low` run completed observation, click and final image verification on a
synthetic native test surface in two tool operations. This verifies actual model
and image/tool transport, not physical Mac execution or CapCut performance.
The broader repository fast suite also ran; existing failures in other app,
model-fixture and repository-policy checks prevent claiming a green full suite.
