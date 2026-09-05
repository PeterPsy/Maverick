# App rail recovery validation — 2026-09-05

## Incident and scope

The reported rail displayed Chat, App Store, and Settings only. The shared
Default workspace still had 26 enabled apps (19 launchable frontends) and its
original 17 pinned IDs. The pin-state `updated_at` remains
`2026-08-31T10:43:54.022355+00:00`: no installation, pin order, or rollout flag
was rewritten to conceal the problem.

The shell had two reproducible failure paths: initial pin discovery was a
one-shot POST, leaving the Chat default after transport failure; an invalidation
failure explicitly replaced already loaded pins with that same default. Late
reads could also overwrite newer reads, reorders, or workspace state.

The fix retains loaded pins and guards/cancels superseded reads. Initial and
refreshed reads now use the app-owned, non-mutating `pinned_apps.read` action,
issued by the SDK's closed `app-store/pinned-apps` request descriptor and run by
the shell's scoped retry coordinator. It never repairs/initializes business
state or emits change events. Existing list/repair and mutation contracts stay
separate; authentication failures still revoke the shell. No generic backend
GET route or unrestricted POST retry was introduced.

## Shared service and published build

- Authorized restart through `core.recovery.restart_backend` completed at
  **21:39:33 UTC**. Main PID changed from `2313062` to `2413916`; health is OK.
- The later rail fixes use app-owned subprocess code and a frontend rebuild;
  they require no second Core restart or changes to other agents' provider work.
- Official Base Shell build, also verified from the live served manifest:
  `96448267645e6924e4af1c44df494bf9787c95893cb4891bea06b45997208574`.
- The user reported that the restart alone did not restore the rail. The final
  frontend fix was published afterwards; on-device confirmation after reload
  remains distinct from the automated evidence below.

## Verification

- Base Shell: **211 tests**, typecheck.
- PWA SDK: **181 tests**, typecheck.
- App Store: **3** read-only entrypoint regressions and **4** real platform
  integration tests, including authentication, unchanged stored pins/events,
  existing repair, ordering, and mutation deduplication.
- Shell mounting contracts: **16 tests**; updated stale assertions left by the
  earlier PWA removal of persisted queued messages/transcripts, without changing
  Chat implementation. Resource inventory: **6 tests**.
- PWA operational audit, unused-import check, and diff whitespace check.
- Disposable Core + real Chromium: **17 rail apps plus Settings**; a forced
  initial HTTP 503 recovers with exactly one bootstrap loader invocation;
  subsequent HTTP 503 preserves all icons; a new pin order is applied. CRM,
  Mail, Calendar, Storage, and Agents report enabled/launchable installation
  state. Test writes affected only the disposable workspace.
- Existing persistent-profile Chromium PWA smoke passed at **22:08:37 UTC**
  against the build above: **16 precache assets**, authenticated Settings cache
  controls on its isolated origin, retained mounted tree during transport loss,
  normal shell restart without network, dynamic-request exclusions, and recovery.

This follow-up build is newer than the previous completion candidate. Earlier
candidate/device artifacts are historical evidence, not physical validation of
this build. Safari/Home Screen physical validation and controlled rollout are
not declared complete here.
