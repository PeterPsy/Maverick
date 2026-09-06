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

## Subsequent startup bottleneck investigation

After the user's confirmation that project labels still fail, access logs showed
repeated client cancellations of initial Chat/backend and provider-setup reads,
at intervals consistent with the SDK's 15-second request deadline. An occasional
expired frame session also went through the existing authorization refresh path.
These observations do not justify weakening authentication or lengthening the
timeout to conceal expensive server work.

Profiling isolated copies of the real JSON provider collections identified an
unnecessary catalog reconciliation in ordinary reads. Both
`workspace_provider_status` and app backend metadata resolution omitted the
already initialized `PlatformState.provider_registry`. Each omission rebuilt a
registry and repeated adoption/reconciliation of the same native catalog.
They now pass the existing registry through the existing resolver API. Fresh
catalog discovery, reconciliation after a catalog change, explicit refresh, and
all certificate/admission checks remain in that resolver; no response cache or
new certification authority was introduced.

Measured on the same host (diagnostic observations, not latency guarantees):

| Measurement | Before | Registry reuse |
| --- | ---: | ---: |
| Provider projection on disposable live-metadata JSON copies, under cProfile | 3.55 s | 1.90 s |
| JSON collection reads in that projection | 862 | 281 |
| Disposable browser cold pin read | 5.91 s | 1.69 s |
| Disposable browser warm pin read | 8.82 s | 1.85 s |
| Disposable browser cold provider setup | 6.43 s | 2.46 s |
| Disposable browser warm provider setup | 7.86 s | 2.66 s |

The real built UI again displayed all fixture pins and the named project after
cold and service-worker-controlled warm loads. At that checkpoint the Core
change still required a backend restart and real-device project labels had not
been rechecked; the operational result is recorded below. WebKit testing is
unavailable on this host because the downloaded fallback browser lacks
compatible system libraries; the browser measurements above are Chromium results.

Startup-fix verification: 408 provider tests and 333 API tests passed, including
the new registry-identity regressions for app backend metadata, ordinary status,
and explicit catalog refresh. The focused app-mount/provider suite passed 63
tests. Unused-import and whitespace checks passed. Codex revision, artifact
digest, operator default, new-pin eligibility, and shared evidence expiry were
rechecked using only in-memory copies and remain unchanged.

## Operational restart and failed project-read recovery

The subsequent authorized restart completed at 08:00:10 UTC on 2026-09-06,
PID 2890750, loading the registry-reuse fix from `de9dbd2e`. `/health` returned
HTTP 200. The official Chat CLI again returned all 27 correctly named projects;
Codex revision 14, digest, runtime version, default binding, and new-pin admission
in the read-only metadata clone remained unchanged. These checks do not prove
that every real-client project read completed: post-restart access logs still
included a cancelled Chat read followed by successful reads.

The user subsequently confirmed that project names were correct after this
restart, before publication of the additional frontend recovery fix below.
The named-project symptom is therefore confirmed recovered on the real client;
the isolated timing measurements are still not a real-device startup latency
guarantee.

A separate deterministic sidebar regression reproduced a persistent symptom:
the catalog read fails, a healthy runtime stream clears the shared `error`, and
all thread project sections remain `Project` without a visible recovery action.
The test failed against the previous hook with an empty error after that stream
update. This demonstrates a frontend recovery defect, not proof that one
particular HTTP failure caused every reported occurrence on the user's device.

Project display reads now have an independent hook and error lifecycle. The
sidebar retains existing names on failure, displays a reload action, and retries
failed non-pending reads on visible focus/online/visibility recovery. It does not
poll healthy or empty catalogs, change the SDK's HTTP retry allowlist, bypass
authorization, or fabricate names for genuinely missing project records.
Revalidation failures are surfaced; superseded callbacks and unmounted reads
cannot replace a newer projection. A project mutation/read-receipt projection
also fences an older pending display read.

The browser regression covers 27 named projects with live thread snapshots,
a delayed failed initial project request, and successful explicit recovery
without page reload, on both 390 px and 1280 px viewports. All four Chromium
runs passed (both widths repeated twice). The focused hook/integration suite
passed 15 tests, including the original negative regression, lifecycle cleanup,
revalidation, empty catalog, and superseded-read cases. Typechecking passed.

Final frontend verification passed 631 Chat unit tests and eight combined
Chromium project-recovery/active-turn steering scenarios. Import and whitespace
checks passed. The previously verified 408 provider and 333 API suites cover
the already restarted Core fix; this additional recovery change is Chat-only
and does not require another Core restart.

The official Chat frontend build published the project-recovery hook with
build ID `608bfc7abee8eff905a8cdea279912280e2bab6371f7eb75a174f42083f61876`,
emitting the normal `maverick.app.frontend-changed` event for mounted clients.
The published artifacts also passed the disposable Core/browser smoke again:
all fixture pins and the named project rendered on cold and service-worker-
controlled warm loads. Post-build `/health` and the read-only Codex compatibility
probe passed, preserving the same revision, digest, executable, and authority.
