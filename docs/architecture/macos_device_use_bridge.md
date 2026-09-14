# macOS Device Use through Maverick

Status (2026-09-14): Codex-only, mono-agent MVP implemented and physically
accepted for functional and performance parity with the retained direct Mac
runtime. The optimized paired A/B measured **4m44s direct** and **4m48s through
Maverick** (**+4s / +1.4%**). The Maverick route passed the complete v40
checklist with one recoverable pre-dispatch `MC-TOOL-14`, no replay and no
duplicate effect. The earlier 4m50s/5m55s pair remains the pre-optimization
baseline.

The native implementation lives in the sibling
`maverick-glasses-ios` repository. Its companion document is
`docs/maverick-macos-device-use.md` there. Keep the two sides and their contract
digest in lockstep.

## Decision and scope

Maverick Chat owns the conversation and Codex runtime. `MaverickMac` is only a
revocable executor for the existing macOS v40 tools:

```text
Chat iframe
  -> authenticated Core activation
  -> native-only broker start
  -> WSS MaverickMac <-> Core
  -> Codex dynamic tool call
  -> existing ComputerTools / Peekaboo / EventKit executor
  -> JSON result plus optional JPEG
  -> same active Codex turn
```

The direct-provider runtime remains available as the A/B control. Device Use
does not copy OpenAI credentials to the Mac and does not expose tool arguments,
results or screenshots to the WebView. JavaScript may request only `status`,
`start` and `stop`; the native app opens the executor WebSocket directly.

The composer button appears only when Chat is hosted by `MaverickMac` and its
native status probe succeeds. A normal browser has no bridge, so the web app
does not render the button.

This route deliberately accepts one runtime shape:

- agent and source app `chat`;
- Codex app-server, model `gpt-6-astra`, effort `high`;
- read-only provider sandbox;
- one agent, without multi-agent orchestration;
- no skills, attachments, app references, MCP servers, project instructions,
  hooks, plugins, shell or filesystem tools;
- dynamic tools `mac_computer`, `mac_peekaboo` and `mac_calendar`.

This narrow envelope is intentional: the benchmark compares the same model,
effort, executor, approved apps and consent policy. Provider expansion and
multi-agent device ownership are not hidden requirements of this MVP.

## Activation and authority

`POST /api/device-use/activations` requires the authenticated browser session
and current native-window generation. Core returns a random bearer ticket valid
for 60 seconds and usable once; only its SHA-256 digest remains in memory.

The native socket presents the ticket and an exact hello:

- protocol `maverick.device-use.v1`;
- executor contract `macos-v40`;
- tool-contract digest
  `c990c06470cb6252edc762a731525b15b0f1f600070c7bc33ab4f15f6c5ae756`;
- model `gpt-6-astra`, effort `high`;
- one selected app contained in the locally approved running-app set.

Core binds the redeemed activation to one workspace, user, browser auth session
and runtime session. A new activation for that login supersedes the previous
lease. Logout, Stop, interruption, navigation/scope change, socket loss,
protocol failure and backend restart fail closed. Persisted sessions never
reconstruct a process-local device lease; start a new Device Use chat instead.

One invocation runs at a time and every invocation is attempt `1`. The native
executor remains authoritative for app membership, observation freshness,
scene/focus ownership, secure fields, confirmations, stop, lock and sleep.
Per-task consent has no time or action-count ceiling inside the exact active
turn and approved app set. Turn end, Stop, lock/sleep, scope change or a blocking
error revokes it. Sensitive external effects still require their dedicated
native confirmation.

## Invocation and image protocol

Each `device_use.invoke.v1` contains the activation/session/turn identities,
provider thread and turn, invocation and call IDs, tool, canonical JSON
arguments plus digest, frozen contract digest, original task text, deadline and
attempt. The Mac hashes the exact argument bytes before parsing them.

The Mac first sends an explicit accepted frame, executes through the existing
v40 `ComputerTools` dispatcher, and returns a validated text result. A successful
observation may additionally return one JPEG. JPEG framing, dimensions, the
4 MB bound, call identity and SHA-256 digest are checked before Core forwards it.
EventKit retains the direct-runtime result budget: the inner result is bounded
at 401 KB and the WebSocket control frame at 512 KB.

For an observation, Core sends one minimal `turn/steer` containing call
correlation and the JPEG, then returns the original text metadata as the dynamic
tool result. Metadata is not duplicated in the steer message, image bytes are
not duplicated in the tool result, and no second model turn is started. Tool
execution stays off the app-server stdout reader so the steer acknowledgement
cannot deadlock.

A disconnect or timeout after dispatch is
`device_use_execution_unknown`. Neither Core nor the Mac retries or replays it.
Codex terminalization sends an ordered turn-end frame, immediately releasing
native observations and per-task consent.

## Fast observation path

`mac_peekaboo.observe_app` is the normal first observation for an approved app.
It is a single read-only native call that:

1. resolves one stable, unique, safe main scene for the exact approved PID;
2. inserts that exact current root `window_id` internally;
3. executes the existing Peekaboo exact-window observation;
4. returns the same snapshot, AX metadata and JPEG as `observe`.

It does not activate the app or weaken any PID/window/scene check. Use
`list_windows` followed by `observe` only when the user targets a specific
non-main window or `observe_app` reports ambiguity. This removes an avoidable
model round trip from the common `list_windows -> choose -> observe` sequence.

The computer tool's long duplicated description was also reduced to a short
summary. The complete consent, recovery, focus and replay rules remain once in
the Device Use base instructions. The model is instructed not to narrate
intermediate progress unless blocked or asked, and to emit a concise final
answer after verification. This does not change executor capability or safety,
but it deliberately changes transcript UX: during an ordinary long run Chat
shows its existing `Thinking` state and the model emits only the final report.
The same instruction is used by the direct control, so the A/B comparison is
symmetric. A user who wants prose updates can ask for them explicitly in the
task; do not add extra model turns merely to synthesize progress.

## Browser and native isolation

The base shell accepts messages only from its registered Chat frame for the
current workspace/login generation and replies through a transferred
`MessagePort`. WKWebView exposes the handler only to the trusted same-origin
main frame. Native validation pins workspace, generation, activation UUID,
ticket bounds and `/ws/device-use/executor`; WSS derives from the configured
HTTPS origin, never caller input.

Tickets do not appear in public status, runtime or thread payloads. Approved-app
identities and raw bindings are private. Screenshots and native payloads never
enter JavaScript or Storage.

## Performance evidence

One complete physical run is sufficient for this MVP because it already
contains dozens of model and native calls. Repeat only after a material code or
environment change.

| Path | Total | Result |
|---|---:|---|
| Direct Mac | 4m50s | PASS CON RECUPERO; 2 `MC-TOOL-14` |
| Via Maverick, pre-optimization | 5m55s | PASS CON RECUPERO; same functional coverage |
| Direct Mac, paired optimized run | **4m44s** | User-measured A/B control |
| Via Maverick, optimized | **4m48s** | PASS CON RECUPERO; 1 `MC-TOOL-14` |

The measured delta is **+65s / +22.4%**. In the Maverick run there were 87
native invocations, 48 Code Mode execution blocks, 49 model samples and 42
observation images. Native host/bridge time was about 23s excluding consent;
one-call bridge p95 was about 519ms, already below the 750ms target. Most of the
remaining time was model iteration, including model cycles between
`list_windows` and `observe`, plus about 30.6s spent producing the final report.

Consequently the current optimization targets tool-call/model-cycle count and
prompt duplication. It intentionally does not add image storage, compression
layers, speculative execution, retries, batching protocols or action+observe
composites.

The optimized physical pair completed with only **+4s / +1.4%** overhead via
Maverick. The Maverick route improved by **67s / 18.9%** from its 5m55s
pre-optimization run and is two seconds faster than the original 4m50s direct
baseline. The paired 4m44s direct run remains the correct control because model
and network variance affect both paths.

The optimized Maverick transcript and local provider log show 77 native
invocations, 41 Code Mode execution blocks, 42 model samples and 42 observation
JPEGs. The images totaled 1,643,980 bytes; median was 26,092 bytes, p95 78,955
bytes and maximum 91,106 bytes. Code Mode host execution totaled 26.44s, with
497ms median and 1,005ms p95 across all operations. That host figure includes
native execution, consent and waits and is therefore not the bridge-only p95;
the retained pre-optimization bridge-only p95 is about 519ms. The ten fewer
native invocations and seven fewer model samples confirm that eliminating the
normal `list_windows -> model selection -> observe` cycle was the material win.

Functional output remained complete: every requested observation, mouse,
keyboard, text, scroll and app-switch phase passed. The single `MC-TOOL-14` was
pre-dispatch, caused no input or mutation, and was recovered by one fresh
observation without replay. No duplicated effect or permission expiry was
reported. On this one deliberately comprehensive execution per route, the MVP
performance and parity gates pass.

Only the Maverick transcript and its private per-session provider logs are
available on Core. The direct transcript and provider logs intentionally remain
on the Mac and do not enter Core; its 4m44s value is the user's paired stopwatch
measurement. This isolation is expected, not missing server telemetry.

## Metrics

While an activation is retained, authenticated
`GET /api/device-use/activations/{activation_id}/metrics` returns no task text,
arguments, output or pixels. It includes per-invocation effect/status, image
bytes and accept/end-to-end/native/relay timings, plus a lazily computed
`summary` with:

- tool and action counts;
- image count and total bytes;
- count, total, p50 and p95 for dispatch-to-accept, bridge end-to-end, native
  execution and relay overhead.

Aggregation happens only on this GET and adds no work to the execution path.
Terminal activations are process-local and retained for roughly ten minutes;
capture metrics immediately after completion and before restarting Core. In the
optimized physical run that window elapsed before the metrics GET, so the
content-free transcript/provider-log counters above are retained instead. Do
not mislabel the all-operation Code Mode host p95 as bridge-only latency.

## Validation and operator runbook

Core, from `/home/ubuntu/projects/maverick-v3`:

```bash
python3 -m unittest \
  tests.unit.providers.test_codex_device_use \
  tests.unit.device_use.test_device_use_service \
  tests.unit.api.test_device_use_api
python3 -m compileall -q core/device_use \
  core/providers/codex_app_server_device_use.py
```

Native structural checks on Linux, from `maverick-glasses-ios`:

```bash
PYTHONPATH=scripts python3 -m unittest scripts.test_mac_integrations
```

The signed Mac runner must then run `swift test`, release build, bundled-runtime
smokes and signing checks. Install only through the existing
`.github/workflows/macos-build.yml` dispatch with `install_and_open=true` while
`MaverickMac` is closed. The installer atomically replaces the same
`~/Applications/MaverickMac.app`; never create a second app bundle.

Current native evidence: commit `dce9d2750cb8` passed **268 Swift tests** and
**35 Python tests**, the credential-free Codex/image and real Peekaboo 4.3.1
smokes, Apple Development signing, same-turn single-JPEG verification and
two-way identity continuity. Install run
[`34850689377`](https://github.com/giuntiocram/maverick-glasses-ios/actions/runs/34850689377)
atomically updated the existing app and requested launch. Its designated
requirement SHA-256 remained
`99971ab861e3c0a730e2e780d47e3da996557ebd4745a445e0f80a7369ccf937`.
This proves build/sign/install integrity, not the remaining physical latency run.

For the physical comparison:

1. verify the button appears only in `MaverickMac`;
2. use the same warm/cold state, account, network, approved apps and consent;
3. run the complete v40 task once direct and once via Maverick;
4. verify all three tool families, same-turn images, stop/lock/socket-loss
   boundaries and no duplicated effect;
5. record wall time, recovery events and the metrics response before restart.

Acceptance is met for the Codex mono-agent MVP: no functional/reliability
regression, no replay or duplicate effect, the previously captured normal
observation bridge p95 below 750ms, and paired total latency within 1.4% of
direct. Keep the direct control available for future material changes; one
complete run per route is sufficient unless code or environment changes.

## Source map and change rules

Core source of truth:

- `core/device_use/contract.py`: model pin, tool schemas, instructions, digest;
- `core/device_use/service.py`: lease, queue, protocol, journal and metrics;
- `core/providers/codex_app_server_device_use.py`: dynamic-tool/image adapter;
- `core/api/device_use_api.py`: activation and metrics HTTP surface;
- `core/api/device_use_websocket.py`: native WSS endpoint;
- `apps/chat` and `apps/base-shell`: composer control and native-only broker.

Native source of truth in `maverick-glasses-ios`:

- `DeviceUseBridge.swift`: WSS contract and lifecycle;
- `IntegratedComputerTools.swift`: shared v40 dispatcher;
- `PeekabooTools.swift`: exact-window and `observe_app` execution;
- `ObservationDelivery.swift`: same-turn image delivery;
- `TaskConsent.swift`: per-action/per-task authority.

When a schema, action, bound or instruction changes: update Core and native
definitions together, recompute the canonical digest, update both pinned digest
constants/tests, run both suites, deploy/restart Core, then build/install the
same Mac app. A digest mismatch must remain a hard connection failure.

Preserve these invariants when adding features: one physical lease, serialized
actions, fresh observations, explicit accepted frames, no automatic replay,
one image per observation, no WebView payloads, native consent as final
authority, and content-free telemetry. Add complexity only for a measured
bottleneck or a required capability.
