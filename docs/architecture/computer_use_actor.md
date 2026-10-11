# Internal computer-use operator

PC use retains one visible conversation and the user's selected planner model.
In delegated mode admitted native providers expose `computer_interact` for bounded UI tasks.
The Core-owned operator uses a separate provider context selected in Settings
under **PC use decision model**, defaulting to Codex `gpt-6.1-sol` / `medium`.
It is not a Chat thread or an inter-agent board participant.
Only read-only UI tools and structured project, code and calendar capabilities
remain directly available to the planner. Native UI input is brokered by Core
through the original activation/session/turn authority, never a copied Mac lease.
Settings also offers direct UI execution by the selected chat model. Direct mode
exposes the complete native tool catalog and rejects `computer_interact`, so the
single-model baseline cannot accidentally start a second model. Connection
registration pins the mode from the verified binding's workspace before new
session persistence; changing mode requires reconnection. Saved operator models
are retained when the default changes.

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
Each screenshot and its textual native receipt are paired in one raw history
message through Codex `thread/inject_items` while the dynamic tool is pending.
The objective and completion criterion are supplied once at context start; each
image carries compact runtime progress and the last two verified effects. Native receipt and target lines are
injected verbatim, with result metadata separate, rather than JSON-escaped inside
one string; line boundaries and current target IDs remain readable.
The tool reply follows only after injection is acknowledged. This does not steer
the active turn or replace its objective. The installed Codex dynamic-tool
`inputImage` response shape alone did not provide reliable visual input in a
live Luna check; the raw `input_image` history path did. Receipt IDs and element
IDs remain observation-specific, and the operator must resolve targets anew.
Immediate post-input captures can precede asynchronous UI updates. Same-target
read-only observations allow that state to settle without replaying the input;
an unchanged immediate capture alone is not proof the mutation failed.
Its catalog always includes native computer, Peekaboo and companion-browser tools.
Actor instructions
retain native UI rules while omitting workspace, project and code guidance that
belongs to the planner. The parent tool lifecycle reports summed native timings
when every delegated operation supplies them.

The planner supplies objective, completion criterion, constraints and an explicit
`prepared_text` list of exact strings to enter. Core rejects actor text absent from
that list. The operator returns verified completion, a decision needed
or a blocker. Its private result explicitly attests whether the entire completion
criterion was met; Core rejects `completed` with a false attestation and strips
that internal field from the planner-facing response. Fresh visual evidence is
still required, and the planner must assess whether it proves the requested
outcome. The operator does not compose content or make business/creative decisions.
Ambiguous input cannot be replayed. Cancellation, parent-turn completion, lease
revocation, owner changes and user corrections fence further actor calls and stop
active inference. Actor failure never transparently replays writes. A configured
recovery model can continue only before input or at a verified structured-step boundary, with no
pending effect or recovery. It shares the task's budget, progress and replay fences;
its actual model, timing and reason are included in attempt metrics. Catalog
availability is checked before launching.
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
recovery permits a fresh observation through the same engine and app.
`MC-INTEGRATION-01` also permits this recovery only when native evidence explicitly
says no action was sent and Full remains active. Invalid parameters then require
a new same-target observation before the operator can correct them; the failure
code alone cannot authorize recovery. Refusals,
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
Absence requires `tabs_complete=true`; a truncated or malformed inventory
cannot prove closure or certify completion.
Unverified completion retains the operator's evidence for the planner to assess.

Actor usage has an internal attribution scoped to the parent session and provider
thread. It contributes to delegated and total usage, while the main model's context
meter remains unchanged. Chat folds internal worker consumption into its ordinary
total without showing another model or delegation; diagnostics preserve the split.
Turn diagnostics include that turn's main and internal operator streams, preserve
the direct/delegated split and main-model context, and exclude other turns and
inter-agent participants. The same projection serves document and SQLite stores.
Deleting the owning runtime also removes its private usage streams.
The workspace-scoped `provider_task_selections` collection persists the operator's
provider, model, reasoning effort, execution mode and optional recovery model/effort
under task kind `computer_use`. This selection
is independent of the conversation model and hosted-provider profiles. Settings
projects it through `/api/settings/platform` and owns the authenticated
`GET`/`POST /api/settings/computer-use` route. Mutations use the existing provider
selection authority, reject another workspace's identity, and validate the provider
catalog and reasoning effort. The UI requires successful discovery and explicit
image modality; an unverified generic model fallback cannot enter this catalog.
It offers image-capable models from the installed
Codex catalog; an unavailable saved model remains visible and blocks operator launch
instead of silently falling back.

Each bounded task captures its selection once. A selection change retires the
private operator before the next task; an active task retains its model. Codex
thread and turn creation use the selected model and effort, disable model fallback,
and attribute usage to that actual model. `computer_actor_factory` is the provider
dispatch boundary: another decision provider requires its own bounded native-tool
operator and catalog integration before Settings can offer it. Only Codex is
implemented today; this setting does not invoke OpenAI's separate Decisions API
or require an OpenAI API key.
Tests cover protocol routing, image delivery, authority, bounded outputs, usage
stream isolation, cancellation and provider-independent tool projection. Performance
claims require a measured matched task; model choice alone is not a speedup result.

## Structured progress and matched evaluation (2026-10-11)

`computer_interact` accepts optional `steps` (at most 32) and `completion_check`.
Runtime progress exposes `completion_verified` and `observation_text_complete`.
If a compact read omits the final predicate, the operator must read the same
window with `details=true` before finishing. A truncated read neither proves
failure nor authorizes replay of an already verified step.
Each step names an engine/target, click/type/replace action, exact control selector
and observable expected effect. Native steps may pin `window_id` from the current
inventory; input and effect verification must then use that exact window, including
verification reads. Text must match `prepared_text`. Runtime-owned
`ui_action` resolves a unique actionable control in a fresh, image-bearing receipt;
it never guesses coordinates or reuses old element ids. Planned tasks cannot
bypass it with raw native input. Pending effects admit only same-target reads;
three unverified reads return a concrete failure without replaying input.
Expected text must equal a visible control label, value, `label: value`, or
standalone receipt line; substring matches do not verify an effect. An already-visible
predicate requires a later read, rather than treating dispatch as proof. Native
recovery and original parent authority remain enforced.

Pixel-only `px1_` observations can carry local Vision text recognized from the same
immutable source capture, with confidence and normalized top-left rectangles.
These are `image_text` labels, never AX elements or writable text focus. A planned
pixel click requires exact label selection and a normalized `region` for both the
target and expected effect. Core resolves one eligible label inside that region
and passes its center through the existing capture-bound `click_point` route.
Confidence below 0.85, invalid geometry, missing/duplicate labels and text input
fail before dispatch. Region-free predicates cannot verify pixel effects: a
Calculator button must not satisfy a result-display check. Native OCR failure
preserves the screenshot with explicit unavailable text metadata. No OCR model
or image transfer to a cloud service is introduced. AX-backed plans and raw
visual navigation keep their existing contracts.

Rejected semantic validation has not sent input: the model gets up to three
actionable corrections to acquire its own observation. Planned tasks renew the
private context after eight images, preserving progress and recovery state;
unplanned tasks keep their history because restarting them could duplicate input.
The same operator process is reused, without giving the model full chat history.
Luna `low` requires a structured plan; its action schema exposes only `step_index`
when a plan exists. Raw-input/semantic validation errors are recoverable before
dispatch, with bounded corrections. An unplanned request dispatches no input
and returns `computer_actor_plan_required`, or routes to the configured recovery
model before inference. The exploratory goal-level evaluation still failed on
Calculator despite successful form/menu runs, so prompting alone does not admit
Luna Low to broad navigation. Recovery after input remains limited to verified
structured boundaries; exhausted budgets cannot launch another process.

`scripts/eval_pc_use_benchmark.py` compares a Sol `medium` planner executing
directly, the same planner delegating to Sol `medium`, and the same planner
delegating to Luna `low` with Sol recovery. All variants receive identical goals,
initial state and 180-second budgets on rendered Calculator, form, menu and
asynchronous-save fixtures. Element ids change on each observation and effects
settle on later reads. An independent state validator requires both Calculator
results, exact form fields, a closed menu, and a persisted title after close/reopen.
Model completion claims alone do not pass. The harness forwards a nested delegation
failure to its root planner as an ordinary tool result, matching the production
parent; a failure may be followed by read-only state verification, without replay.
This is an authenticated model/transport benchmark, not a physical Mac bridge benchmark.

Elapsed time includes planner/operator startup, verification and cleanup. Provider
usage counts every fresh stream once, separates cached/uncached input and reasoning,
attributes actual models, and includes failures/handoffs in time/tokens per success.
No currency cost or pure inference time is inferred from wall-clock duration.
Order rotates between repetitions. Raw output is a temporary measurement artifact;
user reports are delivered through Storage. Run explicitly with:

```bash
python3 scripts/eval_pc_use_benchmark.py --repetitions 3 --timeout 180 --output /tmp/pc-use-benchmark.json
```

## Matched results on 2026-10-11

Final controlled series: three repetitions of each of four scenarios, 36 trials.
The measured execution code is preserved in `c5cf0407`; earlier exploratory runs
are excluded. All figures include the Sol root planner and worker streams,
failures, context renewal, recovery, verification and process cleanup.
Success requires both a completed parent response and independently correct UI
state within the trial budget; correct state alone does not pass a timed-out run.

| Variant | End-to-end success | Seconds per success | Processed tokens per success | Uncached input per success | Cached input per success |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sol direct | 12/12 | 46.8 | 216,082 | 27,394 | 188,032 |
| Sol delegated | 10/12 | 98.4 | 211,207 | 49,438 | 160,499 |
| Luna Low + safe Sol recovery | 12/12 | 58.7 | 210,787 | 48,828 | 160,736 |

Per-scenario cells show successes/runs and seconds per success including failed
attempts. These are controlled fixture times, not native Mac latency estimates.

| Scenario | Sol direct | Sol delegated | Luna Low + recovery |
| --- | ---: | ---: | ---: |
| calculator | 3/3 · 91.9 s | 3/3 · 145.4 s | 3/3 · 111.7 s |
| form | 3/3 · 30.3 s | 2/3 · 65.5 s | 3/3 · 43.0 s |
| menu | 3/3 · 25.4 s | 3/3 · 36.8 s | 3/3 · 31.0 s |
| async-save | 3/3 · 39.7 s | 2/3 · 153.2 s | 3/3 · 49.0 s |

Luna required one Sol recovery on Calculator after a rejected planned-action
call. It is therefore 12/12 for the corrected configuration, not evidence of
12/12 autonomous Luna reliability. Context checkpoints are continuations, not
additional failed trials.

Sol delegated stopped one form before input after two worker observations:
`ui_action` continued to return `computer_actor_fresh_observation_required`.
The original trace does not retain its exact plan/read arguments, so it cannot
establish the source of that mismatch. Subsequent harness runs retain both.
Its last async-save trial reached the independently correct reopened title and
Loaded status, but the parent did not complete before the 180-second budget
(180.464 seconds including cleanup). That run remains an end-to-end failure;
its time and consumption remain in the per-success totals.

This small sample favors Sol direct for responsiveness. Luna with structured
steps and safe recovery remains an experimental alternative. Processed-token
counts are similar across configurations, with more uncached input in delegated
runs; provider billing/prices and cache treatment would be needed to infer monetary cost. These results do not justify general native reliability
claims or changing an existing saved workspace selection automatically.

Final regression: 165 Python tests passed, five SQLite usage variants skipped
because this interpreter is below the verified WAL-safe runtime; 11 Settings
frontend tests and the official frontend build passed. Six benchmark metrics/
fixture checks also passed after adding richer diagnostic traces. The repository
fast suite has failures outside this change in other app, model-fixture and
repository-policy checks, so the full suite is not reported as green.

Physical Mac and desktop/mobile Settings acceptance were deferred by the user
until PC use is reactivated. The runtime changes themselves did not require a
native protocol change; the later physical acceptance uncovered the native
cross-desktop capture defect described below.
The official backend restart was attempted after tests but returned
`authentication_required`: this runtime CLI credential expired at 09:16:18 UTC.
A subsequent authenticated official restart attempt reached the backend but
could not connect to the host systemd bus from the migrated root. After
verifying the exact service cgroup, process identity/ownership and
`Restart=always` configuration, the authorized restart sent SIGTERM to the
existing main process. The host respawned it: PID 1798170 changed to 1970477,
`/health` returned HTTP 200 with `status=ok` and `service=maverick-core`, and
the authenticated official CLI resumed successfully. Backend restart/health
verification is complete; saved-setting and native UI acceptance remain
pending PC use reactivation.

Raw temporary measurement SHA-256: `cb5f9f8fd7b25431d1ea1734e49a899109371a5d74fed217e6f83dc3308ec52f`.

## Physical acceptance on 2026-10-11

The user reactivated PC use with Maverick Mac maximized and Calculator open on
another desktop, then required access to background windows across desktops.
The saved selection was Luna Low with no recovery model. Initial Calculator
observations failed before input (`MC-TOOL-30` / `MC-PEEKABOO-27`), so those
attempts cannot establish model execution reliability or speed. Settings
navigation also exposed a detailed Accessibility tree depth limit: controls
inside the embedded Settings view were missing from the operator metadata.
One theme task was interrupted by user steering; a separate verified task
restored the original Dark mode. These exploratory tasks are not a matched
native model benchmark.

The native 0.3.2 (63) inventory incorrectly described Calculator as on-screen.
Read-only CoreGraphics inspection established that the exact same live window
was present in the all-window list but absent from the active-desktop list.
The bridge required the on-screen flag both for pointer-route validation and
ScreenCaptureKit discovery, preventing an exact observation on another Space.
A read-only capture using ScreenCaptureKit's desktop-independent-window filter
returned the real Calculator pixels without activation or a desktop transition.

Native changes are maintained in `giuntiocram/maverick-glasses-ios`, branch
`maverick-integration`: `c0870a6` adds all-desktop discovery, exact independent
window capture, truthful active-desktop metadata and deeper detailed AX reads;
`c29542b` separates raw-buffer and delivered-JPEG OCR acceptance; `d490045`
updates the signed test reporter for the additional acceptance case. Window
ownership, process birth, geometry checks and fresh observation receipts remain
required before input. Pixel-only observations still authorize pointer input
through an exact captured window, not arbitrary global keyboard input.

The managed runner passed 271 Swift tests. The first signed run found an OCR
assertion that recognized a small glyph in the raw image but missed it in the
delivered lossy JPEG. The second signed run completed 17 cases with zero
failures, then withheld installation because the reporter still expected 16
cases. Managed run `38133327987` at `d490045` passed all gates and installed and
launched 0.3.3 (64) at 10:51 UTC. Its signed evidence lists all 17 completed
cases, including the requested cross-desktop acceptance, with zero failures.
The update disconnected the chat's native session; the next exact-window
inventory returned `device_use_session_not_connected`. Physical cross-desktop
input, foreground switching, general multi-window acceptance and the matched native model
comparison remain pending; read-only capture alone does not satisfy them.

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

Workspace model selection verification on 2026-10-10 passed 95 focused backend
tests and 36 Settings frontend tests, with seven SQLite variants skipped for the
runtime-version requirement. Tests cover persistent workspace isolation, HTTP
authority, catalog admission, selected model/effort on private JSON-RPC, operator
replacement between tasks, usage attribution and stale workspace responses.
The official Settings frontend build passed; the restarted backend reports healthy
and exposes the authenticated settings route. Its live Codex catalog includes Luna
and the `low` effort. The initial physical Mac and desktop/mobile visual checks
were unavailable because the Device Use executor disconnected after restart.

After reconnection on 2026-10-10, 60 focused backend tests and five decision-model
frontend tests passed; seven SQLite variants remained skipped. Core Usage records
the live internal operator as `gpt-6-luna` through Codex. The physical Mac smoke
completed Calculator `1 + 2 = 3` with explicit target guidance and a fresh final
observation. Two earlier `17 × 23` tasks failed: native evidence shows that the
operator selected incorrect digit targets, so these runs do not establish general
target-selection reliability. No model configuration was changed by these checks.
The Mac companion browser reached the actual Maverick Settings URL but showed
the unauthenticated login page. Live Settings save/reload and desktop/mobile
visual acceptance still require an authenticated companion session.

The corrective review on 2026-10-10 passed 99 focused backend tests with SQLite
3.51.3, 41 Settings frontend tests, and all 23 Settings integration tests. The
integration fixture now includes the SDK used by installation hooks, same-origin
proof for cookie mutations and explicit isolated app-frame scope for document
requests; ordinary direct app requests remain denied. A live authenticated Luna
`low` check read the user-provided Settings screenshot correctly through the paired
history path. It used a read-only mock native callback, so physical Mac acceptance
is recorded separately after backend activation.

Physical Settings verification used the authenticated `MaverickMac` work surface
(`com.giuntiocram.maverick.mac`), rather than the unauthenticated companion page.
The UI saved Luna `medium` (labelled Mid), preserved it across an official frontend
reload, then saved and visually verified the original Luna `low` selection.
Immediate post-input captures preceded the selection/save updates; later same-app
observations proved those effects, without repeating the mutations.
The initial post-change physical verification was blocked. The first official
restart returned `restarted=false` because systemd was unavailable in
the execution environment, while backend health remained true. The user later
reported a successful host restart; subsequent native observations returned
`Device Use executor is unavailable`, preventing physical acceptance at that
checkpoint. The earlier physical Calculator retest
was also blocked before input by `MC-TOOL-30` / `MC-PEEKABOO-27`: its visible window
was classified `pixels_only` with no matching Accessibility window. These checks
do not establish unrestricted native-app reliability or a measured latency gain.

After the next reconnection on 2026-10-10, the restarted backend's operator
completed live Settings tasks on the authenticated `MaverickMac` surface. Fresh
observations verified Luna `low`, a temporary save to `medium`, persistence of
`medium` after the official Settings build/reload, and restoration of `low` with
visible save confirmation. A second official build/reload and a read-only task
verified that `low` remained persisted. The desktop panel was readable with Chat
in the right dock; mobile layout was not inspected. Both official builds passed
and left the tracked frontend artifacts unchanged.

The initial save/navigation task returned `blocked` after 23 native operations:
it observed the save confirmation but did not attest the complete Cache/Platform
return criterion. Separate fresh observations and the official reload completed
the persistence check; the partial task was not counted as a pass. The native
Calculator remained inaccessible before input: Peekaboo could inventory its
`pixels_only` window but could not observe a matching Accessibility window, and
the separate computer-engine trial stopped on `MC-TOOL-30`. Consequently the
physical `17 × 23` retest and a physical comparison with Sol remain unverified.
Core's native audit and Usage surfaces recorded the live operations and operator
consumption, but these unmatched tasks do not establish a latency improvement.
The final saved selection remains Luna `low`.

The subsequent Calculator repair identified a native observation defect rather
than an input/model failure. Peekaboo 4.3.1's CLI could capture the exact window
with `--no-elements`, but its MCP `see` schema omitted that mode. Native 0.3.2
(63) now supplies a capture-bound ScreenCaptureKit pixel observation for the
specific read-only AX-incomplete failure; its `px1_` receipt permits only native
`click_point`, with same-window observation and verification after each input.
The public schemas and v52 contract remain unchanged. Source `c157c1d7617c`
passed build/install run `38089725365`, including 16 signed physical-host tests.
The app restart disconnected PC use from this chat. At that post-install
checkpoint the physical Calculator calculations were still unverified; the
user was asked to reconnect. This does not change the saved Luna `low` choice.

After reconnection on 2026-10-11, the installed Mac bundle's `Info.plist`
confirmed version 0.3.2 (63). Fresh observations of the actual Calculator
(`com.apple.calculator`, window 46765) exposed its Accessibility controls and
display, without `MC-TOOL-30` or `MC-PEEKABOO-27`. The initial bounded `17 × 23`
task entered an incomplete sequence and ended at `3`. A subsequent attempt
stopped after clearing, despite a fresh observation proving the display changed
to `0`, because the operator treated `dispatched_unverified` as a blocker.
Neither partial task is counted as a pass.

With an explicit button sequence and a reminder to continue with the next input
once fresh evidence proves the previous effect, the physical Calculator reached
`17 × 23 = 391` and `27 × 14 = 378`. Each intermediate value and both final
results were read from fresh native observations. Core Device Use audit records
the two completed tasks and successful underlying observations/clicks; the
second final display was also independently observed by the planner. No Settings
or model-selection mutation was made. These are guided physical smoke passes,
not evidence of general autonomous target-selection reliability or a latency
improvement. This Calculator session used AX-backed `ps1_` observations, so it
does not directly exercise the new `px1_` fallback; that path retains the signed
physical-host acceptance recorded above.

The matched physical Calculator benchmark later on 2026-10-11 used an identical
two-calculation task (`17 × 23`, then `27 × 14`) for each UI configuration. The
main chat remained Sol; UI execution alternated Luna `low` and Sol `medium`.
With the goal-level request, Luna completed zero of three tasks: failures ended
after 16.638, 161.351 and 34.261 seconds. Sol completed all three in 79.626,
75.038 and 76.411 seconds (median 76.411). A matched guided task specifying all
buttons and intermediate values completed with Sol in 83.598 seconds; Luna
stopped after 23.547 seconds despite observing the expected first digit.
Earlier successful single-calculation smoke tasks are separate observations.

Timings come from Core Device Use audit start/completion timestamps for each
`computer_interact` call. Settings changes, parent task preparation, inter-trial
gaps and report creation are excluded. Both configurations retain delegation;
this is not a single-agent Sol baseline without that boundary. The sample does
not establish a general speedup, cost saving or pure model-processing time.
Luna's failure durations cannot be compared as successful completion times.
Setup encountered popup/receipt failures; fresh state checks established the
selected configuration before resuming, without replaying an uncertain save.
The original Luna `low` selection was restored and its persistence verified.
The Storage-owned report and raw audit/task data are under
`storage/generated/pc-use-benchmark/2026-10-11-calculator-sol-luna.{md,json}`.

Authenticated Codex evaluations used a synthetic native callback with a rendered
calculator, newly numbered element IDs for every observation and delayed input
effects. The fixture has no physical Mac connection. Results were:

| Receipt text | Model / effort | Task | Result |
| --- | --- | --- | --- |
| JSON-escaped | Luna / low | 17 × 23 | Two runs failed to reach 391 within the bounded task. |
| Verbatim lines | Luna / low | 17 × 23 | Reached 391 in 19 calls, with a pre-dispatch recovery. |
| Verbatim lines | Luna / low | 27 × 14 | Incorrect digit targets; task timed out without 378. |
| JSON-escaped | Luna / medium | 17 × 23 | Reached 391 in 15 calls. |
| Verbatim lines | Luna / medium | 27 × 14 | Incorrect digit targets; returned blocked without 378. |
| Verbatim lines | GPT-6.1-Sol / medium | Both calculations | Both reached the expected display in 15 calls, with the correct digit sequence. |

These small evaluations support recommending Sol `medium` for a reliability
trial, not a guarantee of general correctness. Luna remains the saved `low`
selection pending the user's model preference. Receipt readability and stronger
completion instructions do not eliminate model target-selection errors.
The checked-in evaluation also reproduced Sol's 17 × 23 success in 15 calls.

The opt-in evaluation is reproducible, uses existing Codex authentication, and
does not modify the saved workspace selection. It requires the Browser app's
installed Playwright dependency and a local Chromium executable:

```bash
python3 scripts/eval_computer_actor_calculator.py --model gpt-6.1-sol --effort medium
python3 scripts/eval_computer_actor_calculator.py --model gpt-6.1-sol --effort medium --left 27 --right 14
```

Its success exit code requires both `completed` and the correct actual fixture
display. It prints the dispatched labels and observed values, so an incorrect
sequence cannot be hidden by a plausible completion summary. This provider
evaluation is explicit and is not part of the deterministic unit suite.

## Physical acceptance of pixel plans and compact text (2026-10-11)

Core commit `375b5748` passed 117 focused runtime/provider/API tests. Native
commit `a7239f4` passed 277 Swift tests and all 17 signed physical-host cases in
workflow `38140046407`, then installed and opened MaverickMac 0.3.4 (65).
The requested Calculator's exact pixel capture and local text, including `=`,
were verified on its active desktop. This run did not request off-desktop
acceptance and must not be counted as an off-desktop input test.

Before installation, Luna low executed the actual Calculator's `17×23` sequence
in two structured subtasks: four verified steps in 22,598.4 ms and three in
30,259.385 ms. The result was 391. The second subtask returned `needs_decision`
because its final compact read omitted the result, even though a subsequent
detailed AX read confirmed it. This observed failure motivated display-first
compact text and explicit completion/completeness state; it is not a successful
post-fix benchmark or evidence of a speedup.

The installed native update disconnected Device Use. After Core activation,
health returned HTTP 200 with a new backend process, while fresh native inventory
and foreground observations reported the executor unavailable. Post-install
clicks, off-desktop input, multiple windows and matched model comparisons remain
pending reconnection. Storage preserves the report and measured audit snapshots
under `storage/generated/pc-use-benchmark/2026-10-11-pixel-plan-{notes.md,audit.json}`.

## Reconnected physical planned-task evaluation (2026-10-11)

Fresh observations and the running app's Info.plist confirmed MaverickMac
0.3.4 (65). Luna low completed the actual Calculator window 46765's
`19×37 = 703` in 25.691 seconds, then three identical structured tasks containing
`17×23 = 391` and `27×14 = 378` in 57.979, 53.408 and 44.774 seconds
(median 53.408). All 49 clicks across these four tasks were verified by runtime
progress and corroborated by native call counts. The pair tasks each used three
context segments and resumed verified progress at the checkpoints. Measured
native work for the pairs was 6.455, 6.125 and 5.565 seconds. The difference from
task elapsed time is not pure model-processing time.

Setup failures remain separate from the three successful pair trials. An invalid
combined `text`/`role` expectation was rejected before input. An AX plan then met
a pixel-only observation, while the following pixel plan met AX: both stopped
without clicking. Current plans do not declare alternatives across these
representations. Settings reached Platform settings, but its large detailed
receipt omitted later control sections, so no model selection was saved and no
matched post-fix Sol trial ran. The saved Luna low selection remained visible.
The final Calculator inventory still placed the window on the active desktop;
off-desktop input, multiple Calculator windows and a direct single-model baseline
remain unverified. These planned-task successes do not establish general
reliability, comparative speed or per-trial cost. The verified Storage report and
bounded audit/usage data are under
`storage/generated/pc-use-benchmark/2026-10-11-reconnect-evaluation.{md,json}`.
