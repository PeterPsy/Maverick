# Shell and Chat verification after the P5A restart

## Scope and operational state

The authorized Core restart completed at 06:38:07 UTC on 2026-09-06
(`maverick-core.service`, PID 2805199). `/health` returns HTTP 200.
The session-owned Gemini ACP lifecycle from `0ef4940f` is now loaded. That
commit did not change Base Shell, Chat, or the PWA SDK. Gemini remains disabled;
this verification does not enable Gemini or certify Google/OpenRouter.

Read-only official App Store and Chat CLI calls returned the existing 17 pinned
app IDs and correctly named projects. No pin order, project, workspace routing,
rollout flag, or provider authority record was changed during verification.

The official frontend build commands were run again, emitting the normal Core
frontend-changed events for mounted clients:

- Base Shell: `96448267645e6924e4af1c44df494bf9787c95893cb4891bea06b45997208574`
  (unchanged from the preceding rail recovery build).
- Chat: `7ec5d6c778d9b0ee02805f39656cd4b50491ea4b0b83d612ba0e5a3ab22dd8d4`
  (includes the steering action fix and current shared SDK).

## Browser evidence and limits

A disposable Core host with isolated control-plane/workspace data and real
Chromium loaded nine seeded, launchable app pins plus App Store and Settings.
The Chat sidebar rendered the seeded project name, `Named Alpha`. The checks
covered a fresh browser and a reload controlled by the root service worker,
including the Chat data-cache rollout enabled **only on the disposable host**.

A fixed five-second observation initially showed only Chat, App Store, and
Settings after reload. Waiting for the actual read completion restored every
fixture pin without another reload or state mutation. Instrumented warm loads
reported approximately 8–9 seconds for the pin read; the project list also
loads separately from runtime threads. Before it arrives, Chat can display its
generic `Project` placeholder for a thread whose project is not yet known.
The final browser checks wait for named projects and all fixture pins rather
than treating a fixed sleep as readiness.

This reproduces a transient loading symptom, not a proven permanent rail loss
or project rename. It does not establish the cause of the delay. After frontend
publication, the user first reported three icons and then explicitly confirmed
that the rail was complete. Project names were verified on the server and in
the disposable browser. The user subsequently confirmed that the real client
still shows every project as `Project`, with very slow loading, especially at
startup. Those real-client issues remain open at this steering checkpoint;
the isolated fixture does not demonstrate their resolution.

## Steering regression and safety checks

The new mobile browser regression initially failed deterministically: moving
focus from the editor to Send removed the editor-only CSS expansion condition.
The action moved between pointer-down and pointer-up, retargeting the click to
the actions container without calling submit. A CSS-only `:focus-within` change
fixed that transition but failed the additional floating-widget case of sending
a draft after clicking outside the editor, so that experiment was discarded.

Send and Stop now prevent pointer-down's default focus transfer, matching the
existing mobile utility trigger. The action executes only on click, with its
hit target stable for the entire gesture. The current focused or collapsed
layout is preserved without changing CSS. Keyboard focus/activation is not
intercepted. No admission/protocol or Core runtime logic changed.

`apps/chat/tests/e2e/chat-steering.spec.ts` holds a runtime turn active through
HTTP/WebSocket fixtures and submits consecutive messages from the full app,
floating overlay, right dock, and mobile-fullscreen widget, with mouse and touch.
It starts with a focused editor and also sends a draft after moving focus outside
the composer, then submits another message with keyboard activation. It checks
editable/enabled controls, displayed message receipts, distinct client message
IDs, and `steer_or_queue` addressed to the same active turn. No terminal turn
event is sent and no live provider request is made.
This verifies the browser submission boundary. Separately, the user's explicit
steering test was received by this assistant during its active runtime turn.

- Chat unit suite: 622 tests passed, including seven focused Send/Stop pointer,
  focus, and disabled-action regressions.
- Runtime/API message-steering regressions: 14 tests passed.
- New browser steering regressions: 18 passed (six surface/input combinations,
  repeated three times).
- Existing browser smoke: three passed (app boot, normal send, mobile utility
  panels).
- Official frontend builds include both app typechecks.
- Unused-import and diff whitespace checks passed.

A read-only copy of live provider metadata was validated in memory. Codex
profile revision 14 and digest
`33b483337b160ba8281b3ad17176030905ee0b83f2067d5eee911ef6517eab55`
remain unchanged. A new pin was admitted in the clone, preserving the operator's
default and shared evidence expiry. The executable remains `codex-cli 0.153.4`.
No certified Codex adapter module was modified.

The existing mobile utility-panel browser fixture now supplies the runtime
engine role and runtime-backend kind already required by the provider selector.
The fixture previously left the model button disabled; no production provider
eligibility check was relaxed to make the browser test pass.
