# Per-app Maverick sidebar presentation

The shell previously opened its detail panel on desktop rail hover/focus for
every launchable app, regardless of widget declarations. Design Studio declares
no sidebar widgets, so that produced an empty panel with shell controls. The
global fixed preference also reserved detail-panel space for it.

`presentation.sidebar_enabled` now controls this behavior. It defaults to true;
the canonical serializer preserves false and omits true. Design Studio declares
false. Other existing app contracts keep the enabled default. Core transports
the boolean through `/api/apps`; Base Shell applies the declaration of the
resolved active app, including fallback navigation. The shell waits for app
metadata before mounting sidebar widgets during startup.

Apps opting out keep the app rail, with workspace/current-app settings above
its shortcuts and branding/theme/global sidebar preferences below them. The
two compact menus open on hover or keyboard focus, support pointer/touch, and
dismiss with Escape, outside clicks or focus leaving the group. Mobile exposes
both groups through the existing header menu. Opt-out suppresses sidebar-open
requests, widget mounting, resizing and fixed-panel spacing. The user's global
fixed/overlay preference survives switching back to an enabled app; previously
mounted enabled-app widgets retain their independent lifecycle.

The bundled creator/design skills, their enabled persistent workspace copies,
SDK documentation and contract architecture describe this choice. Workspace
skills were updated through the Skills app and read back; their ids, enablement
and origin metadata were preserved.

## Verification

- Full Base Shell Vitest suite: 41 files, 267 tests passed. After the final
  startup/fallback and menu-focus changes, the five affected files passed
  75 tests, including two additional startup/fallback regressions.
- Focused parser/presentation/canonical/sidecar-contract tests: 33 passed.
- API integration confirms false reaches the registry for an arbitrary app
  installed under different public, local and mount ids.
- `npm run test:sidebar-presentation`: built-shell Chromium fixture passed at
  1440×900 and mobile 390×844. It checks widget-discovery suppression, hover
  continuity into menus, viewport bounds, Escape, theme changes, restoration
  of fixed spacing on app switches, mobile taps and header-menu dismissal.
  App-frame documents and sidecars are intentionally outside this fixture.
- Desktop/mobile screenshots were inspected; shell controls fit the viewport.
- Official `maverick app base-shell frontend build --json` completed with
  TypeScript validation and a frontend refresh event. Committed dist is updated.
- Unused-import check and `git diff --check` passed.

The broader app-hosting run has unrelated failures: Calendar's manifest
entrypoints need `dateutil` in the Python interpreter running that suite; a
TLS integration test patches the removed `ensure_browser_origin_tls` symbol;
and a sidecar workspace-isolation fixture returns 503. Five existing static
shell/Chat source assertions also fail identically against committed HEAD and
the working tree. These were isolated from the focused feature checks.

## Runtime activation

The official backend restart was attempted through
`core.recovery.restart_backend`. It returned `restarted: false` because this
environment is not booted with systemd. Its health probe remained healthy at
`http://127.0.0.1:8014/health`. The running Uvicorn process has no reload flag;
the new Core parser/registry still require a managed restart. Browser app smoke
at `http://hostmachine:8014/app/design-studio` verified shell transport only;
it does not establish authenticated activation of the new contract. No manual
detached replacement backend was started.
