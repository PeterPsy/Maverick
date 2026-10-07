# macOS Device Use through Maverick

Status (2026-09-15): **the only macOS execution path**. Maverick Chat and Core
own the model turn; `MaverickMac` is only the signed native executor. The old
local/direct Codex mode, local transcript, credential provisioning, native setup
chrome and Chat execution switch have been deleted without a compatibility
shim.

The final paired v40 acceptance test took **4m48s through Maverick** and **4m44s
direct** (+4s / +1.4%) with equivalent functional coverage and no replay. The
direct path was then removed. The current executor contract is `macos-v47`.

The native implementation lives in the sibling `maverick-glasses-ios`
repository; its companion source document is
`docs/maverick-macos-device-use.md`. Keep both sides synchronized.

## Mac-local coding companion (v48)

The additive contract `macos-v48` has digest
`5682ddabb352ada6e227e2294e8026ae3f47ce095e3de9466aab11627d6a5b8d`.
Reviewed explicit idle reconnection from v47 retires the old provider context
while preserving chat, owner, workspace and On/Full mode. Core must be deployed
before the matching native client; unknown digests remain rejected.

Full PC use now includes `mac_code`: a native folder picker, persistent chat-owned
coding bookmarks, guarded UTF-8 read/write/replace, directory listing/creation,
and local shell jobs with opaque handles, independent output pagination, stdin
and stop. The native app remains an executor; Core still owns the model,
transcript, credentials, tool ledger and encrypted evidence. No provider runtime
is copied to the Mac, and no server permission is inherited from native access.

The selected cwd confines file-tool paths but is not a shell sandbox. Native
consent explicitly states that commands have the user's macOS permissions and
network access. The motor runs `/bin/zsh -c` with an explicit local environment,
without Terminal, global input or app activation. Core's wire calls remain short
(180s; picker 300s); the native command has its own 1–3600s lifetime budget.
Transport success and exit success are separate in result facts.

Jobs are owned by the active chat/turn and stop on turn completion, Stop, lock,
disconnect and app exit/crash. A signed bundled command host monitors a lifetime
pipe and monotonic deadline, terminates the shell group/ordinary descendants,
and removes leftover group children after shell completion. Deliberate detachment
is unsupported. There is no automatic replay. File writes use expected hashes,
exclusive creation and atomic replacement; there is no universal filesystem lock
against concurrent user writes. Existing bounded media primitives remain shell-free.

Native 0.2.0 (51) also packages the user's supplied SVG as AppIcon.icns and assigns
the running Dock image. Verification and installation evidence follow the managed
runner build; native-picker interaction is separate from automated project fixtures.

## Product contract

### Parallel companion on the same macOS (2026-10-07)

The native 0.1.6 / build 50 companion runs on the user's existing macOS. The
user explicitly rejected a second macOS. A separate native-owned headless
Chrome/Edge process has its own persistent profile, tabs, fixed viewport and
logical cursor; targeted CDP events never move the physical pointer or activate
user windows. A nonactivating read-only native preview shows the cyan secondary
cursor. A native sign-in command opens only the dedicated profile while PC use
is off. No VM, personal-profile attachment, provider runtime or credential copy
is introduced.

The fifth dynamic tool, `mac_browser`, provides companion tab management,
HTTP(S) navigation, exact-tab observations and receipt-bound input. It rejects
file/JavaScript/browser-internal URLs and exposes no arbitrary script/CDP entry.
Focus verification precedes typing; one receipt admits one gesture; navigation,
Stop and turn boundaries invalidate receipts. Transport loss/uncertainty cannot
replay an action or fall back to the desktop. Chrome/Edge must be installed.
Native file chooser/upload and downloads are unsupported by this tool.

Version 47 addresses the multi-tab/scroll regression from the authorized test
thread `39dd8328-e73f-489a-b50e-9cb31dbd787b`. The private renderer is activated
before observation/input and actual tab selection. Wheel amounts use CSS pixels
(default 300, maximum 10000); omitted coordinates default to the viewport center.
A single RPC timeout/cancellation retires only its waiter, preserving the browser
and all tabs. Socket loss fails pending commands without replay; a fresh read
reattaches to the same owned process and invalidates old sessions/receipts.

`mac_peekaboo.launch_app` requests nonactivating NSWorkspace launch by installed
bundle ID. Native apps retain control over their own windows and can activate
themselves; this does not promise private native views. `click_point` is a primary
window-targeted CGEvent route rather than an AXPress fallback. It binds the
kernel process birth identity, exact visible normal-layer window and unchanged bounds
to capture, revalidates immediately before dispatch, pairs down/up synchronously,
and never warps the cursor or sends global input. An input reported as
`dispatched_unverified` can satisfy `observe_after` by returning a fresh exact
window image; delivery does not claim the intended effect. Unknown/partial
outcomes still require the same-app verification boundary without replay.
Schema failures identify the field without echoing private input values.
Provider guidance asks agents to store plain observation metadata rather than
image-bearing tool wrappers; the functions.exec storage implementation is
outside the native/Core bridge and has not been changed.


Companion is enabled by default in the native menu. While enabled, global
`mac_computer` input/activation is rejected before dispatch; `select_app` only
changes internal targeting. Native Peekaboo retains strict background delivery,
and EventKit/project APIs remain independent of cursor/focus. Arbitrary native
apps can still share document/view/app-internal focus with the human: complete
independent browser views do not imply general third-party app virtualization.
An explicitly selected shared-desktop mode revokes the current lease first.

The additive contract is `macos-v47`, digest
`d0405d09ac1ff6903336a7fa7427c7c28e2922167a0dfe302a4db0bc48b00c71`.
Core admits companion images through its existing WSS/binary JPEG path and
adds companion guidance to both provider adapters. Full admits the browser;
bounded On retains existing native scope and cannot use it. Reviewed v44/v45/v46
conversations can upgrade only by explicit idle reconnection, retiring provider
context without changing their model or On/Full binding. Deploy Core before
installing this native contract. The companion source document owns native
module/resource/lifecycle details and physical acceptance results.

The repair was installed on `MacBook-Pro-6` on 2026-10-07 as native 0.1.5
(49), revision `f945e1eb9487`. Build run `37665013284` and explicit install run
`37665247139` each passed 260 generic Swift tests, all 7 tests in a signed
physical host with empty failure diagnostics, and 37 Python script tests.
The physical tests cover multi-tab scrolling, preservation through an RPC
timeout and socket reconnection, trusted browser input, nonactivating native
launch and an exact custom-drawn window click without global pointer events.
Read-only diagnostic run `37665584494` confirmed the installed revision, valid
signature and one process running the installed copy. Core's 74 focused bridge,
provider and API tests passed before deployment; the managed backend restart
returned healthy. These checks do not assert a completed CapCut workflow or
independent native app views.

The follow-up authorized Chat test `c8cf3203-dc54-484d-b648-bbbc85820cd3`
completed all five requested steps with the installed 0.1.5 executor. Its
complete audit contains 36 native calls and 25 archived images: companion
observations confirm Roma/Milano titles, 600-pixel scrolls and returns to the
top, a Venezia search result, closure of the search tab, and retention of the
original tab IDs after CapCut. CapCut started/reused its existing PID with
`activation_requested=false`; one custom-drawn Home click opened a new editor.
Subsequent observations confirm the Text panel and timeline duration changing
from zero to `00:00:03:00` after adding default text. The agent reported the
clip in both the timeline and preview.

Two calls were safely rejected or left unverified and recovered through fresh
observations: browser typing was rejected before dispatch when the focused
field's signature changed; the project-opening click's immediate
exact-window observation failed after Home was replaced by a new editor window.
The agent used `observe_app` and did not repeat the uncertain project click.
No global-input/activation tool calls, browser timeouts, lost tabs, unknown
executions, imports or exports appear in this audit. This is a successful
browser/basic native-app workflow; the audit does not independently measure
physical cursor/foreground state or establish independent native app views.

Detailed review found a separate keyboard defect masked by the successful
workflow: the agent's Return key did not submit the Wikipedia search, so it
used the search button. A controlled Chromium form reproduces zero submissions
with the old key-down/key-up payload, versus one trusted submission when Return
includes `text` and `unmodifiedText` as carriage return. Native 0.1.6 (50) sends
that character with Return's key-down and uses `rawKeyDown` for other named keys.
The signed browser acceptance now checks Tab/Shift-Tab focus traversal and one
trusted Return form submission, in addition to the existing input/scroll and
transport checks. Tool schemas and the `macos-v47` contract are unchanged.

Native revision `dca46011672635c151623d9c412f0cb7a2836865` passed all 260
generic Swift tests, 7 signed physical-host tests and 37 Python script tests in
explicit install run `37674354930`. It installed and launched 0.1.6 (50) on
2026-10-07. Signed results had zero failures and empty diagnostics, including
the new keyboard assertions. Read-only diagnostic run `37674654669` confirmed
revision `dca460116726`, valid signature and exactly one process running the
installed copy. Core required no implementation/schema change or restart.

The additive workspace-chat correction was deployed on 2026-10-07 from Core
commit `b30e63a4`, followed by a healthy managed backend restart. Native build
0.1.4 (48), revision `6fca24f26f24`, was installed and opened on `MacBook-Pro-6`
by GitHub Actions run `37659756971`. The runner passed 265 Swift and 37 Python
tests, verified the Apple Development signature and update identity continuity,
and reported the installed version running. Core/provider/API regression tests,
88 Chat unit tests, the official Chat frontend build and the PC use browser
checks at desktop/mobile widths passed. These checks cover chat admission,
normal workspace context and native authority; they do not assert a physical
cross-app business workflow was completed.

The Mac app is a chrome-free WebView of the ordinary Maverick Chat. There is no
native status/setup toolbar and no `Sul server` / `Su questo Mac` selector. Chat
renders its Device Use control only when the trusted macOS bridge answers the
status probe; browsers never render it.

The native window, `WKWebView`, overscroll surface, and every WebKit frame use
Maverick's dark loading background from construction and inject the same
first-paint color at document start. The web shell replaces it with the
selected theme when ready; a default white WebKit canvas is never a loading
state.

The composer exposes one **PC use** toggle beside Research and the other
composer utilities. It shares their icon-button style, `aria-pressed` state and
active label:

- switched on, it starts the existing **Full** native/Core authority;
- switched off, it revokes the native/Core lease and prevents further device
  calls, including while a turn is running.

There is no three-way selector or app-scope/consent settings modal. macOS
permission requests remain available under **Maverick → Permessi PC use**
while access is off. The emergency **Interrompi PC use** command retains
`Shift-Command-.`. OS permissions and the existing Full executor's technical
limits still apply.

Mode remains immutable when a Device Use chat is materialized. Disconnected or
stopped Full chats reconnect through the same toggle. Historical bounded On
chats retain their original binding and can be stopped; the new control cannot
reactivate or promote them, so Full requires a new chat. Ordinary existing chats
also require a new chat to enable device access.

Chat probes native/Core status on navigation, foreground return, turn state
changes and every ten seconds while visible. Historical mode never implies a
live connection. Only the first submission of a draft with PC use selected
requires a ready lease before materialization. Existing chats can submit ordinary
workspace work while the Mac is stopped or disconnected; native tool invocation
checks the lease independently.
Custom agent chats preserve their agent identity, prompt, skill selection and
source app when adding Mac access. Admission validates the ordinary workspace
runtime and the authenticated native activation; app provenance is not a Mac
permission gate. Same-turn Codex corrections keep the normal structured skill
inputs and explicit skill-mention handling while updating the native task text.

These review regressions were fixed in Core commit `468bc54b`, published on
2026-10-07 and activated by a healthy backend restart. Verification passed 73
Core/API/provider tests and 40 Chat frontend tests. Native 0.1.5 (49), revision
`8ff8297b8aaf`, was rebuilt, signature-verified, installed and opened by Actions
run `37666482424`; its runner passed 260 Swift tests and seven signed physical
acceptance cases. Native execution uses the existing contract without changes
to the Mac binary for these Core corrections.

Turning off and back on explicitly renews an idle Full conversation, including
when provider context has been lost. Renewal is rejected while a turn is running;
turning off remains available. Stop only clears the local activation once Core
or the native executor confirms revocation; if both fail, the active state and
activation ID are retained and an error offers the native emergency stop.

REST and WebSocket thread catalogs, including the bounded display cache, retain
the public activation ID and original On/Full mode. They omit native credentials
and live readiness. Selecting a cached Device Use thread without that summary
loads its authorized detail before enabling a mode; missing metadata never
defaults to On. Explicit reconnection publishes the updated catalog binding so
other Chat views keep the new lease ID. This is a Core/Chat change and retains
the native transport; the current paired contract is `macos-v47`.

## Architecture

```text
MaverickMac WebView / Chat iframe
  -> authenticated one-shot Core activation
  -> trusted base-shell broker (control metadata only)
  -> native WSS MaverickMac <-> Core
  -> native provider tool call
  -> CompanionBrowser / ComputerTools / Peekaboo / EventKit executor
  -> JSON result plus optional binary JPEG
  -> same active provider turn and transcript
```

Model ownership, provider credentials, conversation state, image injection and
audit remain in Core. WebKit exposes only `maverickDeviceUse`; live invocation
arguments, results, screenshots and credentials do not travel through the bridge
JavaScript. The separate owner-authorized audit UI can explicitly fetch historical
results and images through Core; credentials and typed input text are withheld.
The retired `maverickLocalRuntime` handler and broker do not exist.

The v46 executor retains one native execution path, with two existing Core
provider adapters:

- source app and agent `chat`;
- Codex app-server uses dynamic tools and same-turn image steering with the
  model profile and reasoning effort already selected in Chat;
- Antigravity CLI uses its existing private `maverick-device-use-mcp` wrapper,
  forwarding the same five tools to Core's Device Use invoke API;
- the native app remains a single executor, without provider runtime or
  credentials;
- Mac control supplements the ordinary workspace agent. Both Codex and
  Antigravity retain platform/agent instructions, workspace skill selection,
  app CLI access, attachments, app references and delegation;
- Codex retains the ordinary managed runtime home, workdir and execution policy,
  adding the pinned native tools and Mac-specific developer instructions. The
  bundled code-mode host handles native dynamic calls; ordinary server requests
  continue through the standard provider handler;
- Full grants Mac authority independently of server/workspace permissions. Stop
  and disconnect deny native calls, while ordinary provider prewarm and workspace
  turns remain available. A turn from another owner/login revokes the native
  lease while leaving ordinary workspace admission intact. Collaborators never
  inherit the native binding;
- Research remains its separate web-only profile and cannot acquire Mac access;
- one native `mac_project` capability is limited to a user-picked media project.

Compatible models from these admitted native families use the ordinary model
selector. The Antigravity adapter was added before v44; v44 does not broaden
provider or multi-agent authority. Its HTTP wrapper uses the same operation
budget plus Core result-delivery grace and 10 seconds of client margin, rather
than aborting every media operation after 200 seconds. Other provider families
require a separate design.

## Off, On and Full authority

### Off

No activation or device lease exists. Selecting Off stops both Core and native
sides when an activation is present.

### On

On preserves the bounded v40 policy:

- the chosen running app plus at most 23 additional running apps form the exact
  allowlist;
- start requires native approval;
- mutations use per-action confirmation or one unlimited per-task consent;
- sensitive effects keep their explicit confirmation and secure fields remain
  unavailable;
- ordinary blocking diagnostics latch the current turn;
- Stop, known lock/sleep/session/display invalidation or scope loss revokes;
- Core admits at most 512 unique calls in one turn.

Observation receipts, scene/focus identity, point hit-testing and non-replay are
mandatory in both modes.

### Full

Full is an explicit operator break-glass mode. Policy deliberately imposes:

- no app allowlist; the handshake app list is discovery only, and every current
  or newly launched running application is eligible;
- no start, per-action, per-task or sensitive-effect confirmation;
- no unique-call, action-count or elapsed-time ceiling;
- no secure-field exclusion in the native computer input path;
- no blocking turn latch after ordinary app/focus/tool/display failure;
- no revocation on sleep/wake, Space, display or active-session changes.

**Only explicit Off/Stop or a positively detected screen lock revokes Full
policy authority.** Full does not treat missing/malformed lock-state metadata as
proof of lock. Turn-end clears ephemeral observations and receipts but does not
revoke the underlying Device Use lease.

Unavoidable inability to execute is not an authorization limit: macOS TCC
permissions must exist; a terminated process cannot receive input; a sleeping
machine cannot execute until it wakes; app quit, Core loss, WSS loss, hardware
failure or process termination can make the executor unavailable. Bounded
wire frames, one-shot tickets, exact call identity, deadlines for a single
transport operation and image validation protect protocol integrity; they are
not user-facing request/action quotas.

## Activation and binding

`POST /api/device-use/activations` requires the authenticated session and the
current native-window generation. Core returns a random bearer ticket valid for
60 seconds and usable once; only its digest remains server-side. The Mac opens
the WSS directly and sends:

- protocol `maverick.device-use.v1`;
- executor `macos-v47`;
- tool digest
  `d0405d09ac1ff6903336a7fa7427c7c28e2922167a0dfe302a4db0bc48b00c71`;
- mode `on` or `full`;
- initial app and the running-app discovery/allowlist snapshot.

v41 added mode to the hello, ready frame, immutable `DeviceUseSessionBinding`,
public thread projection and provider instructions. v42 removed the
executor-level model pin. v43 adds the governed `mac_project` tool and therefore
changes the frozen tool digest. v44 keeps the same schemas/digest and aligns
native/Core media deadlines while improving precise timebases and cancellable
sampling. Runtime session creation still records the
selected Codex model and effort in the ordinary immutable
`RuntimeExecutionBinding`, and both thread/start requests read that binding. In
On, Core validates the initial app against the admitted list and applies the
call ceiling. In Full it does neither.

A binding is exact to activation, user, workspace, runtime session and contract.
Only one activation per login generation and one physical call at a time are
allowed. A new activation supersedes the prior lease. Tickets and raw private
bindings never appear in public thread/status payloads. Compact public thread
catalogs expose `device_use_enabled`, the public activation ID and original
On/Full mode so Chat can label, filter and reconnect the conversation without
receiving tickets or native authority material.

`POST /api/device-use/sessions/<session_id>/reconnect` accepts a fresh ready
activation and the expected previous activation ID. It requires the owning user,
workspace and current login, an existing Device Use chat, the same mode and wire
contract, and the same initial app/app set in On. Full's running-app discovery
snapshot may change. The persisted session lifecycle fence excludes active,
queued and confirmation-waiting turns. A field-only CAS changes the native lease
without overwriting session metadata or its immutable model/execution binding.
Late cleanup of an older provider cannot unregister the renewed activation.

Device Use Codex threads have a durable archive in the session's private
`codex-home`. A later provider process resumes the same thread while keeping
the pinned model, ordinary workspace workdir/policy, native tools and independent Mac lease.
Provider termination after completion therefore does not require a Chat reload
or lease renewal before the next message. A connected native lease retains its
idle provider process so a navigation/pause does not discard model context. An
idle lease check uses the shared deadline scheduler, separate from the ordinary
workspace process budget; it releases the retained process after disconnection.
An idle/completed provider exit never revokes the independent Mac lease; an exit
during unfinished work still revokes it because execution may be unknown.
Explicit reconnection closes the old idle provider and clears only its mutable
continuation IDs. The first subsequent turn restores bounded, redacted visible
human/agent text through the ordinary classified provider-input capture. It keeps
the current request separate, excludes raw tool calls/results, tickets, images
and receipts, and instructs the model to observe current state before continuing.
No message POST, native operation or uncertain action is automatically retried.
The current paired wire contract is `macos-v47`; the installed executor is compatible.

## Invocation and image transport

Each invocation carries exact activation/session/turn/provider/call identities,
canonical JSON arguments and SHA-256 digest, frozen contract digest, original
task text, attempt `1` and a bounded operation deadline. The native side sends
an explicit accepted frame before executing.

Successful observation returns one bounded text result and, when present, one
separately framed JPEG under 4 MB. The same binary route carries the single
timecoded contact sheet produced by `mac_project.sample_frames`. Core validates
the exact admitted tool/action, framing, call identity, dimensions and digest,
injects the JPEG into the same Codex turn with one minimal `turn/steer`, then
releases the original text tool result. For the existing Antigravity adapter,
Core's invoke API returns that same image to the private MCP wrapper, which
projects one MCP image content item in the active provider call. Image bytes
are not sent through the WebView or stored by the relay. EventKit retains the 512 KB control-frame bound.

## Governed project media

`mac_project` is the sole v45 filesystem exception. `authorize_project` opens a
native directory picker and persists a security-scoped bookmark behind a random
opaque `project_id`. Neither Core nor the model receives an absolute path.
Every later argument is project-relative; absolute paths, traversal, symlinks,
CapCut application-support/package/database roots and paths outside the selected
folder fail closed.

Source media is read-only. Native writes are limited to:

```text
<project>/
  .maverick/
    analysis.json
    transcript.json
    scenes.json
    silences.json
    edit-plan.json
    verification.json
    scripts/
    working/
  output/
```

The admitted actions are `authorize_project`, `inspect_media`,
`transcribe_media`, `sample_frames`, `detect_scenes`, `detect_silence`,
`prepare_subclip`, `generate_srt`, `verify_media` and `run_project_script`.
AVFoundation performs inspection, sampling, analysis, non-destructive range
composition and output verification. Speech transcription is on-device only
and fails closed when the selected locale has no on-device recognizer.
`run_project_script` persists and executes a bounded JSON list of the same
approved operations; it never evaluates source code, invokes a process, opens a
shell, delivers secrets/environment values or grants network access. Outputs
carry SHA-256 evidence, and source hashes are rechecked across transforming
operations.

A disconnect or timeout after dispatch is `device_use_execution_unknown`.
Neither side retries or replays it. A fresh observation may establish outcome;
a mutation is repeated only when new state proves it did not occur. Terminal
turn handling clears native per-turn observations and On consent in order.

`mac_peekaboo.observe_app` is the fast normal observation: it resolves and
captures one stable exact main window in one read-only call. Use
`list_windows` plus `observe` only for explicit alternate-window selection or
ambiguity. Persistent WSS, one serialized invocation, one JPEG, no Storage hop,
no polling, one GUI input per invocation and no speculative execution are
deliberate performance invariants. Explicit `observe_after` attaches one fresh
same-window capture to that input; it never repeats or sequences GUI inputs.

## Source map

Core:

- `core/device_use/contract.py` — v46 identity, tool schemas and On/Full prompts;
- `core/device_use/models.py` — immutable mode binding;
- `core/device_use/service.py` — activation, lease, serialization, ledger,
  binary images and On-only quota;
- `core/api/device_use_api.py` / `device_use_websocket.py` — HTTP activation and
  private executor WSS;
- `core/providers/codex_app_server_device_use*.py` — dynamic-tool and same-turn
  image adapter;
- `apps/base-shell/frontend/src/deviceUseBroker.ts` — trusted control broker;
- `apps/chat/frontend/src/components/DeviceUseControl.tsx` — binary composer toggle;
- `apps/chat/frontend/src/hooks/useDeviceUse.ts` — activation lifecycle.

Native:

- `DeviceUseRuntime.swift` — native activation, permissions and revocation lifecycle;
- `DeviceUseBridge.swift` — v46 WSS and binary image transport;
- `ComputerTools.swift` / `IntegratedComputerTools.swift` — dispatcher;
- `CompanionBrowser*.swift` / `CompanionPreview.swift` — owned browser, exact-tab input and independent preview;
- `ProjectAccess.swift` — native picker, opaque bookmarks and path confinement;
- `ProjectTools.swift` / `ProjectMedia*.swift` — bounded media operations;
- `DesktopSessionMonitor.swift` — On invalidation and Full lock-only monitor;
- `NativeTextFocus.swift` / `NativeTextInput.swift` — exact input admission;
- `PeekabooTools.swift` / `CalendarTools.swift` — GUI and EventKit motors;
- `App.swift` / `MacWebView.swift` — chrome-free app and sole native bridge.

Do not recreate local transcript, provider runtime, Codex binary bundle,
credential copy/provisioning or a second chat execution mode on the Mac.

## Validation and release procedure

Core focused checks:

```bash
python3 -m unittest \
  tests.unit.device_use.test_device_use_service \
  tests.unit.device_use.test_device_use_continuation \
  tests.unit.providers.test_codex_device_use \
  tests.unit.api.test_device_use_api \
  tests.unit.api.test_inter_agent_api
python3 scripts/check_unused_imports.py
maverick app chat frontend build --json
maverick app base-shell frontend build --json
```

Native Linux structural checks:

```bash
python3 -m unittest discover -s scripts -p 'test_mac_*.py'
```

The Apple-silicon workflow must also run Swift tests, release build, real
Peekaboo catalog smoke and signing/designated-requirement checks. Deploy/restart
Core before installing a v46 Mac client. Dispatch the existing workflow using
`install_and_open=true`; the installer requests normal Quit if MaverickMac is
running, then atomically replaces `~/Applications/MaverickMac.app`. Never create
a second app bundle.

Unit/CI checks prove contract and build integrity, not physical GUI behavior.
After material executor changes, one complete real task is sufficient because
it already contains dozens of model/tool calls; record total time, recovery,
replay/duplicate effects and bridge metrics before restart.

## Accepted performance evidence

| Path | Total | Result |
|---|---:|---|
| Via Maverick, pre-optimization | 5m55s | Complete with recoverable failures |
| Direct control, paired final run | **4m44s** | Complete |
| Via Maverick, paired final run | **4m48s** | Complete; one pre-dispatch recovery |

The final delta was **+4s / +1.4%**. The optimized Maverick run used 77 native
invocations, 41 Code Mode blocks, 42 model samples and 42 observation JPEGs;
ten fewer native calls and seven fewer model samples than the earlier run were
the material improvement. The persistent binary bridge itself was not the
bottleneck. Do not add compression layers, upload indirection, retries, polling,
batching or compound action/observe tools without new measurement.

Core projects every dynamic native call as a redaction-safe
`runtime.tool_call.started` plus `completed` or `failed` lifecycle. Chat uses
those events to show the current Mac action and the persisted Actions group;
raw arguments, typed text, screenshots and native result bodies stay private.
The model may add brief milestone narration, but should not narrate every click.

## v44 media correctness and operation budgets (2026-09-30)

Project calls use the same budget on Core and Mac: 5 minutes for ordinary
media operations and the native folder picker, 15 minutes for transcription or
subclip export, and 20 minutes for a declarative script. Other native tools
retain their 3-minute wire deadline. Core allows a further 5 seconds for result
delivery; Stop or disconnect still unblocks the worker immediately and never
replays a call. A cancelled picker closes without persisting a new bookmark.

Authorization returns a bounded inventory of project-relative media files
(128 files / 1,024 visited entries / depth 8), excluding symlinks, packages,
hidden files and generated output. `inventory_complete=false` means there may
be additional media; never infer that the returned list is exhaustive.

Inspection exposes each track's native timebase and minimum frame duration.
Subclips convert start and end independently using the source track timebase,
reject collapsed ranges, retain the precise source tick manifest, and replace
generated exports atomically. They do not infer constant frame rate for
variable-rate media: use the actual timestamps returned by frame sampling.
Asynchronous image generation is cancellable and returns actual CMTime values
and timebases. Hash streaming and audio scanning yield execution rather than
blocking the native UI; full source hashes remain checked across transforms.
The complete Speech result is persisted; there is no silent 2,000-word cap.
The wire result may return a marked partial transcript to stay within its bound.

Verification samples eight frames without rendering or JPEG-encoding an unused
contact sheet, fails on detected black samples, and rechecks the file hash
after sampling. `valid=true` covers the requested dimensions/fps/duration and
those samples only. It is not proof of the whole video, audio quality, captions
or a CapCut preset; audio reporting is track presence only. Inspect targeted
contact sheets, run audio analysis as needed, and observe CapCut for creative
acceptance. Intentional black samples require review, not an automatic pass.
SRT generation rejects overlapping captions and intervals that collapse to the
same millisecond before writing.

Automatic tests and signed installation are separate from the blueprint's
CapCut acceptance: a real authorized source, the Marco Shorts preset, final
export inspection and three consecutive measured successful runs are still
required before claiming CapCut 1.0.


## v45 CapCut report corrections (2026-10-06)

The report in Chat `ab031d45-5bb7-49bc-a889-3e797a8a22dd` is the regression
source. Three exports from one timeline do not establish three independent
end-to-end passes. Neither lower failure rates nor faster completion are claimed
from automated tests alone.

The additive tool contract is `macos-v45`, digest
`0b96e1a3013c1bfece055623d8b104cd029b1b8ebb21719686999531abbf424d`.
Explicit idle reconnection permits the reviewed v44 digest
`d525d61fc31a5d873b189166be26d90bd613dc1e2e430f69a07744d920ea4dd1`
to upgrade to v45. It retires the old provider context, retains the execution
binding/history, and preserves owner, workspace, protocol and On/Full scope.
Other version transitions are rejected. Deploy Core first, then install the
matching native client. The installer requests normal Quit only for an explicit
install; if the app does not close it refuses replacement. Xcode and its checkout
are untouched.

| Finding | Implemented correction | Regression evidence |
| --- | --- | --- |
| P0 window identity | Remember the last visible owner-bound primary; recover missing AX metadata only with a prior root or one unique visible primary. Associate a tiny Finder rename overlay with its uniquely containing document. Auxiliary roles/frames and inference basis are returned. | Native window/scene and recovery tests; ambiguity remains a precise failure. |
| P0 repeated picker/reconnection | Persist chat-to-project opaque ID beside security-scoped bookmarks. `resume_project` returns inventory and checkpoint without a picker. `save_checkpoint` uses CAS revisions and explicit export stages. Disconnected native sessions reject every native family while retaining ordinary workspace prewarm and turns. | Checkpoint, project binding, Core reconnection and offline-prewarm tests. |
| P0 uncertain input | Consume receipts before dispatch; unknown, partial, suspected no-op and transport loss require same-app observation in On and Full, across turn boundaries. No other engine or input can bypass verification. | Peekaboo recovery tests including Full and end-turn. |
| P1 late prerequisites | `preflight` batches at most 24 sources, durations, hash duplicates, inventory coverage and local Speech capability. Empty inventory fails early; unavailable analysis is distinct from absent speech. Preset/project GUI checks remain explicitly unverified until observed. | Media/cache and validation tests. |
| P1 redundant decisions/rounding | Hash-bound inspection reuse, whole-frame CFR subclip preparation and output fps/duration check. Compact AX observations with `details=true`; `observe_after=true` performs exactly one input then captures the same window, without replay. | Native 30fps multi-range fixture and bridge image-admission tests. |
| P1 limited quality checks | Planned cut samples at ±one frame, optional all-frame decode up to 120s, timestamp discontinuities, repeated imagery, black frames, decoded audio peak/RMS, clipping, silence, gaps and duration mismatch. | Generated media pipeline tests. Technical validity does not certify captions, preset, lip sync or creative quality. |
| P1 inaccessible/overwritten audit | Encrypted per-call results/images, official paginated CLI/MCP reads and owner/admin HTTP readback. Immutable project evidence paths retain every analysis; failures identify step/field, completed steps and result artifact. | Audit encryption, paging, image integrity and tenant/owner denial tests. |
| P2 stale requirements/prewarm | Same-turn steering preserves ordinary workspace/skill input and updates native task context with the acknowledged latest correction. Failed automatic prewarm has a 60s cooldown. Native user wait is separate from execution and transport. | Steering, cooldown and timing tests. |

### Project and quality evidence

`resume_project` requires an existing bookmark for the same chat or an explicitly
supplied previously authorized opaque ID. A v44 installation did not store a
chat-to-project association: its first v45 authorization can require one picker;
thereafter the association survives native restart and lease renewal. A revoked
or stale bookmark is never replaced by guessed filesystem access.

Checkpoints store a bounded latest requirements revision, project label, relative
destination/edit plan, last verified step and one stage: `planning`,
`timeline_ready`, `export_dialog_open`, `export_started`, `file_present`,
`file_verified`. They are historical hints, never GUI receipts or proof that an
interrupted export succeeded. A resume observes the real app and inspects the
existing destination before deciding whether to continue.

Artifacts live below `.maverick/working/evidence/<uuid>/`; each analysis,
transcript, edit plan, verification and contact sheet has a new path. Named
`.maverick/scripts/` definitions remain explicitly replaceable. Final media stays
below the selected project's `output/`, with its relative path/hash in evidence.
The native executor does not transfer arbitrary local files to Storage; a workflow
requiring a workspace deliverable must use a separately authorized Storage flow.

Speech reports `speech_detected` or `speech_absent` only after successful local
recognition. Missing locale/engine/permission reports `analysis_unavailable` and
must not trigger repeated attempts until capability changes. There is no cloud
fallback. GUI requirements, such as a mandatory CapCut preset, are checked before
editing and cannot be satisfied by a generic media verification.

Full-frame scans decode every frame but sample a 32×18 luma grid in each frame;
repeated signatures and silence need comparison with the intended edit. Audio
clipping timestamps are bounded with explicit completeness. No automated result
claims perceptual listening, caption synchronization or lip-sync acceptance.

### Authorized audit and timing

`core.runtime.device-use.audit.read` returns paginated lifecycle summaries by
thread, keyed by `turn_id` and `call_id`, including native failure versus invalid
media. `core.runtime.device-use.call.read` returns bounded encrypted evidence
windows. `/api/runtime/turns/<turn_id>/device-use-audit?call_id=...` serves the same
owner/admin evidence, and `image=true` returns JPEG with `Cache-Control: no-store`.
Chat loads evidence/screenshots only on explicit inspection.

Runtime events contain only opaque evidence references and safe facts. Blobs use
Core's context-bound AES-GCM private store, 2MiB blob and 128MiB session quotas;
JPEGs are chunked. Typed text is withheld even from audit owners. Capture failure
never triggers physical input replay. Old calls honestly report unavailable
private evidence; provider log files are not a readback fallback.

`native_duration_ms` includes `native_user_wait_ms`; subtracting the latter gives
native execution. The turn remainder is `outside_native_ms`, not model time.
Bridge elapsed/overhead and image bytes are separate. Token/cache totals remain
owned by Core Usage and its coverage/accuracy markers; missing provider timing or
image-token breakdown is unavailable, never estimated from wall time.
Legacy or mixed history with missing clock/image measurements returns `null`
for incomplete totals and derived execution/overhead, lists the unavailable
metrics and reports measured call counts. Missing user wait is never zero wait.

Release verification for this correction passed 104 focused Core/API/provider
tests, the additional native-outcome and legacy-coverage audit regressions,
and 41 Chat tests.
Native commit `8a70575fab71c2345d19119582de3ea068a5ee2f` passed 259 Swift tests,
the release build, native catalog smoke and stable signing checks in Actions run
`37489843667`. The broader Core fast suite has unrelated failures reproduced
on the pre-change revision; it is not reported as passing.
Explicit install run `37492029914` built the same native commit, passed the
259 tests and signing checks again, and confirmed `Installed and running:
0.1.2 (45)` on the managed runner. Physical CapCut acceptance remains separate.

Acceptance on the connected Mac must distinguish build/unit tests from actual
CapCut trials: five silent clips; spoken footage with pauses/repetitions and
captions; Space/fullscreen changes; disconnect during export; exact import/frame
rate; absent required preset. Repeat independent projects and compare total/phase
times, model/tool calls, recoveries and manual interventions. The report's target
of fewer than 5% failures and half as many model/tool round trips is a measured
acceptance objective, not an asserted outcome of this patch.

## PC use toggle release (2026-10-07)

The binary control uses Full at start and verified revocation at stop. Desktop
attachment, utility and runtime controls stay on one row; long model labels
truncate without separating the attachment plus. The browser regression
reproduced a 42px vertical separation before the fix and verifies centers within
1px afterward. Mobile keeps its existing upward Utility panel. Focused
verification passed 91 Chat tests, 17 Core Device Use tests and two real-browser
native-frame tests at 900px and 390px. Those browser tests verify the exact Full
start request and both stop requests; their native executor is a test fixture.
The broader existing Chat smoke still expects the obsolete `Default Chat` agent
label where the current product uses `Free Agent`; it is not reported as passing.

Native commit `b612d8049edc322c4f13784022bbec9961768b0a` passed 259 Swift tests,
release build, native catalog smoke and stable signing checks in Actions run
`37639586942`. Its explicit install completed with `Installed and running:
0.1.2 (46)` on `MacBook-Pro-6`. Physical GUI control and macOS permission
retention are separate from the build, installation and browser-fixture checks.
