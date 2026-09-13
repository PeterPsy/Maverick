# macOS Device Use through Maverick

Status: Codex-only, mono-agent MVP implemented for A/B evaluation. The Core,
Chat and native bridge tests pass in the Linux checkout. A signed macOS build
and physical end-to-end run are still required before this path is production
evidence.

## Decision

Maverick Chat owns the conversation and Codex runtime. `MaverickMac` is a
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

The old direct-provider runtime remains available as the A/B control. Device
Use does not copy OpenAI credentials to the Mac and does not put tool arguments,
results or screenshots through the WebView. JavaScript can only request
`status`, `start` and `stop`; the native app opens the executor WebSocket
directly.

The composer button is rendered only after the macOS native bridge returns a
positive availability response. The ordinary browser has no bridge and never
renders it.

## MVP envelope

This route deliberately accepts exactly one runtime shape:

- agent and source app: `chat`;
- runtime engine: Codex app-server;
- model: `gpt-6-astra`;
- reasoning effort: `high`;
- execution mode: read-only sandbox;
- one agent, no multi-agent orchestration;
- no skills, attachments, app references, MCP servers, project instructions,
  hooks, plugins, shell or filesystem tools;
- dynamic tools: `mac_computer`, `mac_peekaboo`, `mac_calendar`.

This is narrower than the long-term multimodel design on purpose. It makes the
benchmark compare the same model, effort, native executor, app set and consent
policy as the direct Mac path. Extending provider codecs or multi-agent
ownership is not part of this MVP.

## Activation and authority

`POST /api/device-use/activations` requires the current authenticated browser
session and a bounded native-window generation. Core returns a random bearer
ticket valid for 60 seconds and usable once. The ticket is retained only as a
SHA-256 digest in memory.

The native socket must present that ticket and then an exact hello:

- protocol `maverick.device-use.v1`;
- executor contract `macos-v40`;
- frozen tool-contract digest
  `6135e7975fc6d510723fc146c76133f1fb3c23a5a4d9b53935c5149d4c477752`;
- one selected app contained in the locally approved running-app set.

Core binds the redeemed activation to exactly one workspace, user, browser
auth session and persisted runtime session. A second binding is rejected. A
new activation for the same login supersedes the earlier lease. Logout,
explicit stop, runtime cleanup, turn interruption, native disconnect, protocol
failure, timeout and backend restart all fail closed. Persisted sessions never
reconstruct the process-local executor after a restart.

Device sessions may continue only while their exact pinned Codex authority and
ephemeral native lease remain live. They never enter the generic compatible
continuation/fork path, because a successor without the same physical lease
would silently become a workspace runtime. Start a new Device Use chat instead.

The current MVP intentionally uses an ephemeral one-use activation rather than
a durable paired-device credential. Stable device enrollment, offline device
inventory and reconnect are follow-up work, not hidden properties of this
implementation.

## Invocation protocol

Core serializes physical work through one bounded executor queue. Every
`device_use.invoke.v1` contains:

- activation, runtime session, Maverick turn, provider thread and provider turn;
- invocation and provider call IDs;
- tool, a bounded canonical JSON argument string and its SHA-256 digest;
- frozen contract digest;
- original user task text for native per-task consent;
- deadline and fixed attempt `1`.

The Mac acknowledges receipt, invokes the existing v40 `ComputerTools`
dispatcher and returns one validated text result. Observations additionally
send a separately framed JPEG with invocation/call identity and an independently
checked image digest. Images are bounded below 4 MB and validated as a
single-frame JPEG on the Mac.

Text results preserve the direct v40 executor budget: EventKit may return just
under 200 KB before the result is wrapped. The native/Core WebSocket control
frame is therefore bounded at 512 KB and the validated inner result at 401 KB,
covering worst-case JSON escaping plus fixed envelope fields without making the
relay unbounded.

The Mac hashes the exact canonical argument bytes before parsing or executing
them. When Codex reaches a terminal turn, Core sends an ordered turn-end frame
so native observation state and per-task consent are released immediately.

Core injects the JPEG with `turn/steer` while the same Codex tool call is still
pending, then releases a text-only tool result. Tool execution is handled off
the app-server stdout reader so the steer acknowledgement cannot deadlock. A
disconnect or timeout after dispatch is `device_use_execution_unknown`; Core
never retries or replays it.

The native executor remains authoritative for app membership, observation and
snapshot freshness, focus, scene ownership, secure fields, local per-action or
per-task consent, sensitive-effect confirmation, stop, sleep and lock
invalidation. The Core bridge does not weaken those checks.

## Browser and native isolation

The base shell accepts Device Use messages only from its registered Chat frame
for the current workspace and login generation. Replies use a transferred
`MessagePort`. Unknown fields are stripped before calling the native handler.

WKWebView exposes the message handler only to the same-origin main frame. The
native command validator pins the workspace, generation, exact activation UUID,
ticket bounds and exact `/ws/device-use/executor` path. The WSS URL is derived
from the configured HTTPS origin; callers cannot supply another host.

Activation tickets are never returned by status endpoints, runtime session
payloads, thread payloads or native status snapshots. The raw persisted binding
and approved-app identities are removed from public runtime serialization;
public status exposes only the app count. Device instructions are injected only
into the private ephemeral Codex thread.

## Measurement

`GET /api/device-use/activations/{activation_id}/metrics` returns content-free
per-invocation evidence for the owning browser login:

- dispatch-to-native-accept time;
- dispatch-to-result time;
- bridge end-to-end time;
- native execution time reported by the Mac;
- derived relay overhead;
- JPEG byte count, effect class and terminal status.

It never returns arguments, task text, tool output or image bytes. Run the
comparison with the same Codex account, `gpt-6-astra`, high effort, approved app
set, consent mode, initial app state and network. Separate cold and warm runs.
For deterministic transport comparison, issue the same v40 action sequence in
both paths; for agentic comparison, repeat the same natural-language task and
record total duration, tool count, errors and recovery.

Suggested MVP acceptance thresholds remain:

- total median no worse than direct +10%;
- total p95 no worse than direct +20%;
- normal-observation bridge overhead p95 below 750 ms;
- no reliability regression, duplicate effect or replay.

Do not remove the direct runtime until physical A/B runs meet those thresholds.

## Physical acceptance checklist

1. Build and sign the macOS package on Apple silicon; run the full Swift suite.
2. Open Chat in `MaverickMac` and verify the Device Use button is absent in an
   ordinary browser but present in the native app.
3. Select the same approved app set and consent mode used by the direct path.
4. Exercise all three tools: foreground observe/control, Peekaboo exact-window
   observe/control and EventKit read/write/readback.
5. Verify same-turn screenshot interpretation, then stop during a pending local
   confirmation and during a dispatched action.
6. Verify logout, navigation, screen lock, sleep, socket loss and Core restart
   revoke the lease with no replay.
7. Inspect network traffic: native image bytes go only to Maverick Core; Core is
   the only component forwarding them to Codex/OpenAI.
8. Export the metrics endpoint and execute cold/warm deterministic and agentic
   A/B runs against the retained direct mode.

Unit tests and a Linux frontend build are not evidence that macOS permissions,
signing, physical actions or provider latency passed this checklist.
