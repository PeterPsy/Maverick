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
Its catalog always includes native computer, Peekaboo and companion-browser tools.
Actor instructions
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
Each queued Codex native request retains the task text, binding, parent identities
and objective revision captured on receipt. A correction increments that revision
before cancellation, native turn-end or provider I/O. Requests received while the
correction is pending cannot gain authority after acknowledgement. Dispatch and
every operator call recheck the frozen authority, even when thread/turn ids or task
text are unchanged. Each subtask owns its cancellation event; admitting a new
subtask cannot clear the cancellation of its predecessor.
A rejected or uncertain correction keeps native admission fenced until a
correction is acknowledged or a new parent turn is admitted; subsequent calls
from the provider's old goal cannot acquire the new revision.

Native failure is terminal unless its contract declares recovery. Peekaboo
`MC-PEEKABOO-25/27` requires a same-bundle window-list refresh followed by a fresh
observation. `MC-PEEKABOO-20/21/23` permits only same-bundle Peekaboo reads until
an observation with an image succeeds; the operator then reasons from that image
and must stop if the intended effect is absent or ambiguous. A new receipt cannot
authorize replay of the same uncertain input. Peekaboo input identity uses the
action, app and fields that determine its actual effect (target, text, key or
scroll parameters). Receipt and observation-only arguments (`window_id`,
`observe_after`, `details` and `image_max_dimension`) do not authorize another click.
The partial outcome `MC-PEEKABOO-22` permits same-bundle read-only verification only when the native result explicitly
declares that Full remains active and requests a fresh observation. Explicit native pre-dispatch
recovery permits a fresh observation through the same engine and app. Refusals,
unknown failures, engine/app changes during recovery and unverified completion
remain blocked. Final evidence preserves recovered native failure codes.

Companion `MC-COMPANION-03/04` recovery is restricted to a read-only observation
of the exact affected tab. A successful image unlocks distinct actions;
`MC-COMPANION-04` also fences replay of the uncertain input even with a new
receipt or changed observation options. An uncertain tab creation without a
known target remains blocked. Native post-input capture failures are classified
as uncertain effects, never as proof that input was not sent. Completion requires
fresh image evidence or a validated native companion tab inventory, which can
verify a closed tab's absence without a screenshot of a nonexistent page.
After an uncertain close, that inventory is also an allowed recovery read and
settles the pending effect only when it proves the exact tab is absent.
Unverified completion retains the operator's evidence for the planner to assess.

Actor usage has an internal attribution scoped to the parent session and provider
thread. It contributes to delegated and total usage, while the main model's context
meter remains unchanged. Chat folds internal worker consumption into its ordinary
total without showing another model or delegation; diagnostics preserve the split.
Turn diagnostics include that turn's main and internal operator streams, preserve
the direct/delegated split and main-model context, and exclude other turns and
inter-agent participants. The same projection serves document and SQLite stores.
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

Regression verification on 2026-10-10 includes 194 passing tests covering native
authority, queued and active corrections, bounded recovery, private actor
JSON-RPC, usage, provider lifecycle and API/MCP routing. Another 35 tests were
skipped because the available SQLite 3.46.1 is below the verified WAL-safe
runtime requirement; the new turn-usage checks also have SQLite variants for
that runtime. This regression run uses simulated native tools and does not
measure physical Mac or CapCut performance.

The follow-up recovery review is covered by 84 passing focused tests, including
same-target replay with changed observation options, numeric point identity,
partial outcomes with and without declared recovery, and anti-replay after explicitly authorized
Full verification. The partial-outcome classification matches the current native
`PeekabooFailure` and `ComputerTools.failureMessage` contract; protocol tests use
simulated native results and do not exercise the physical Mac.
