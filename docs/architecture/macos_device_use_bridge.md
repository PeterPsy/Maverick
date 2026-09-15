# macOS Device Use through Maverick

Status (2026-09-15): **the only macOS execution path**. Maverick Chat and Core
own the Codex turn; `MaverickMac` is only the signed native executor. The old
local/direct Codex mode, local transcript, credential provisioning, native setup
chrome and Chat execution switch have been deleted without a compatibility
shim.

The final paired v40 acceptance test took **4m48s through Maverick** and **4m44s
direct** (+4s / +1.4%) with equivalent functional coverage and no replay. The
direct path was then removed. The current executor contract is `macos-v42`.

The native implementation lives in the sibling `maverick-glasses-ios`
repository; its companion source document is
`docs/maverick-macos-device-use.md`. Keep both sides synchronized.

## Product contract

The Mac app is a chrome-free WebView of the ordinary Maverick Chat. There is no
native status/setup toolbar and no `Sul server` / `Su questo Mac` selector. Chat
renders its Device Use control only when the trusted macOS bridge answers the
status probe; browsers never render it.

The composer control mirrors the Usage badge style:

- its computer icon opens the settings modal;
- **Off** revokes the active native/Core lease;
- **On** applies the configured app list and confirmation mode;
- **Full** enables all control the executor can technically perform.

The modal owns the On settings and macOS permission entry points. Mode is fixed
when a new Device Use chat is materialized. Off may stop that chat, but a stopped
or already-bound thread is never rebound; start a new chat to choose On or Full.
The native application menu retains the emergency **Interrompi Device Use**
command (`Shift-Command-.`).

## Architecture

```text
MaverickMac WebView / Chat iframe
  -> authenticated one-shot Core activation
  -> trusted base-shell broker (control metadata only)
  -> native WSS MaverickMac <-> Core
  -> Codex dynamic tool call
  -> ComputerTools / Peekaboo / EventKit executor
  -> JSON result plus optional binary JPEG
  -> same active Codex turn and transcript
```

Model ownership, provider credentials, conversation state, image injection and
audit remain in Core. WebKit exposes only `maverickDeviceUse`; arguments,
results, screenshots and credentials never pass through JavaScript or Storage.
The retired `maverickLocalRuntime` handler and broker do not exist.

The v42 path deliberately remains one provider/runtime family:

- source app and agent `chat`;
- Codex app-server with the active model profile and reasoning effort already
  selected in Chat;
- one agent, Device Use tools only;
- no skills, attachments, app references, multi-agent mode, MCP servers, shell
  or filesystem tools during a Device Use turn.

Every active Codex model exposed by the ordinary Maverick model selector is
therefore usable without a second Device Use selector. Hosted and generic tool
loop providers are not admitted because this bridge depends on Codex dynamic
tools and same-turn image steering. Provider-family and multi-agent expansion
require a separate design; do not add speculative abstraction to this path.

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
- executor `macos-v42`;
- tool digest
  `c990c06470cb6252edc762a731525b15b0f1f600070c7bc33ab4f15f6c5ae756`;
- mode `on` or `full`;
- initial app and the running-app discovery/allowlist snapshot.

The tool schemas did not change from v40, so the digest is unchanged. v41 added
mode to the hello, ready frame, immutable `DeviceUseSessionBinding`, public
thread projection and provider instructions. v42 removes the executor-level
model pin: runtime session creation records the selected Codex model and effort
in the ordinary immutable `RuntimeExecutionBinding`, and both thread/start
requests read that binding. In On, Core validates the initial app against the
admitted list and applies the call ceiling. In Full it does neither.

A binding is exact to activation, user, workspace, runtime session and contract.
Only one activation per login generation and one physical call at a time are
allowed. A new activation supersedes the prior lease. Tickets and raw private
bindings never appear in public thread/status payloads.

## Invocation and image transport

Each invocation carries exact activation/session/turn/provider/call identities,
canonical JSON arguments and SHA-256 digest, frozen contract digest, original
task text, attempt `1` and a bounded operation deadline. The native side sends
an explicit accepted frame before executing.

Successful observation returns one bounded text result and, when present, one
separately framed JPEG under 4 MB. Core validates framing, call identity,
dimensions and digest, injects the JPEG into the same Codex turn with one
minimal `turn/steer`, then releases the original text tool result. Image bytes
are not duplicated, stored or sent through the WebView. EventKit retains the
512 KB control-frame bound.

A disconnect or timeout after dispatch is `device_use_execution_unknown`.
Neither side retries or replays it. A fresh observation may establish outcome;
a mutation is repeated only when new state proves it did not occur. Terminal
turn handling clears native per-turn observations and On consent in order.

`mac_peekaboo.observe_app` is the fast normal observation: it resolves and
captures one stable exact main window in one read-only call. Use
`list_windows` plus `observe` only for explicit alternate-window selection or
ambiguity. Persistent WSS, one serialized invocation, one JPEG, no Storage hop,
no polling, no batching and no speculative execution are deliberate performance
invariants.

## Source map

Core:

- `core/device_use/contract.py` — v42 identity, tool schemas and On/Full prompts;
- `core/device_use/models.py` — immutable mode binding;
- `core/device_use/service.py` — activation, lease, serialization, ledger,
  binary images and On-only quota;
- `core/api/device_use_api.py` / `device_use_websocket.py` — HTTP activation and
  private executor WSS;
- `core/providers/codex_app_server_device_use*.py` — dynamic-tool and same-turn
  image adapter;
- `apps/base-shell/frontend/src/deviceUseBroker.ts` — trusted control broker;
- `apps/chat/frontend/src/components/DeviceUseControl.tsx` — composer control
  and modal;
- `apps/chat/frontend/src/hooks/useDeviceUse.ts` — activation lifecycle.

Native:

- `DeviceUseRuntime.swift` — Off/On/Full settings and lifecycle;
- `DeviceUseBridge.swift` — v42 WSS and binary image transport;
- `ComputerTools.swift` / `IntegratedComputerTools.swift` — dispatcher;
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
Core before installing a v42 Mac client. With MaverickMac closed, dispatch the
existing workflow using `install_and_open=true`; the installer atomically
replaces `~/Applications/MaverickMac.app`. Never create a second app bundle.

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
