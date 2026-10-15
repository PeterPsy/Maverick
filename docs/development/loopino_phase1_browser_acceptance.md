# Loopino phase 1 authenticated browser acceptance

2026-10-15, production HTTPS installation `https://loopino.giuntitrail.com`.
This closes the authenticated browser smoke and host-layout checks listed in
the activation checkpoint, within the tested scope below. It does not claim
complete feature coverage, real-device PWA acceptance or native Apple acceptance.

## Method and coverage

Admin authentication succeeded. The official Browser app created bounded,
Core-authenticated developer-inspector contexts for desktop (1440 x 1000)
and mobile (390 x 844). Navigation, accessibility snapshots, screenshots,
console and network evidence were collected through the declared Browser tools,
including the isolated app and OpenDesign frames. No arbitrary browser script,
vendor patch, impersonated role or copied browser profile was used.

All 20 launchable app frontends were inspected in both viewports:

| Apps | Coverage |
| --- | --- |
| Chat, Storage, Agents, Skills, Settings, Vault, App Store | Authenticated loading, populated/empty states, desktop/mobile layouts |
| Calendar, Mail, CRM, Memory, Checklist | Authenticated empty-workspace views and navigation |
| Browser, OpenWA, Docs Studio | Setup/connection state, gateway state and readable documentation |
| Dynamic Views, Fitness Coach, Senses | Empty workspace/device state and controls |
| Website Studio | Empty workspace, successful snapshot API after correction |
| Design Studio | Unchanged native UI, local Codex profile, desktop execution and mobile host layout |

The installed inventory contains 26 apps; supporting shell/devkit/widget
frontends and backend-only apps were not assigned artificial launch routes.
The public catalog endpoint is `/catalog/api/apps`, returns 200 and lists 26
apps. The unimplemented `/catalog` and `/catalog/index.json` paths are not
catalog failures.

Functional checks passed:

- Desktop Chat submitted a temporary message and received exactly
  `LOOPINO_BROWSER_OK`; floating-chat continuity across app navigation worked.
- The mobile app drawer opened and navigated to Storage. Storage opened its
  Generated folder. The mobile model picker displayed the enabled Codex and
  Gemini choices; disabled provider choices were preserved.
- Navigation between apps remained usable without returning to installation
  setup.
- Design Studio selected the installed local Codex profile. A real native run
  completed in 6.4 seconds after the sandbox correction and returned the test
  marker (underscores are rendered as Markdown emphasis by the native UI).
  This tested the separate model bridge rather than a Loopino Chat fallback.
  No design files were generated.

## Corrections applied

- `fcea2fd3`: Vault and the Design Studio host now reserve the shell's mobile
  top offset. Website Studio's SDK display snapshot explicitly requests no
  app secrets, preventing HTTP 500 when no GitHub grant exists. Actual Git
  import, synchronization and publishing retain their declared grants.
  Website snapshot requests then returned 200 on desktop and mobile.
- `43a873f6`: the model-access sandbox mounts only the resolved Codex executable
  read-only at `/model-cli/codex`. Private toolchains outside `/usr` now run
  without exposing their parent directories or the installation tree.
- The Core service now explicitly supplies the protected native executable and
  authorized installation login source using
  `LOOPINO_MODEL_ACCESS_CODEX_BIN` and `LOOPINO_MODEL_ACCESS_CODEX_HOME`.
  Core and the Design Studio sidecar were restarted through their supported
  control paths. The native package and its data model were not modified.

The regression tests were observed failing before the corresponding fixes.
Final checks passed: 210 PWA-cache tests plus typecheck, 39 Website Studio
frontend tests, 15 Design Studio frontend tests and 29 Core model-access tests
(293 tests total). Official frontend builds completed for Vault, Website Studio,
Base Shell and Design Studio. Unused-import and whitespace checks passed.
The first Base Shell build was interrupted; its standalone official retry
completed. An initial pytest invocation was unavailable; the Core suite ran
successfully through its existing unittest runner.

## Boundaries and remaining acceptance

- OpenDesign's official mobile UI still clips parts of the working-directory
  control and model popup at 390px. The host/header collision is fixed; these
  remaining native layout limitations were not patched in the upstream bundle.
- Optional native OpenDesign requests to AMR, GitHub/community, AIHubMix media
  discovery and the Vela message center returned 500/502. Local Codex execution
  succeeds, while the aggregate model-bridge state remains degraded because
  no API model transport is configured. Native cloud/media/community features
  and a complete Design Studio feature acceptance remain unverified.
- The Browser Lab blocks service-worker registration. Real PWA installation,
  offline behavior, device permissions, capture, push and microphone/camera
  behavior therefore remain real-device acceptance items.
- Mail/Drive/OAuth, WhatsApp pairing and a user Chrome companion on the new
  installation were not connected merely for the smoke test. Their empty
  connection states are expected. No messages or emails were sent.
- Signed Apple clients and hardware acceptance remain open. Mac configuration
  stays last. Predecessor data migration and phases 2/3 were not performed.

Transient harness failures are retained in private evidence: one stale Storage
ref after view-state synchronization and network-idle timeouts on pages with
ongoing polling. Subsequent snapshots verified the resulting UI state.
Console/network logs are cumulative and were reviewed by timestamp and URL,
rather than attributing earlier failures to later apps.

## Evidence and cleanup

Private redacted operational evidence is under
`operations/phase1/browser/`: snapshots, PNGs, request logs, checksums,
model-access configuration metadata, test output and cleanup receipts.
It is excluded from source commits; credentials are not included in reports.

The temporary UI smoke chat and native OpenDesign project were deleted through
their owning APIs/UI. Browser contexts were closed, their no-turn runtime
fixtures and issued tokens were cleaned, and the two pre-existing user chats
were preserved. Browser state remains owned by `loopino` with mode 0600.
Core, Browser and OpenWA were active after the final checks.

Selected screenshots and an Italian report are delivered through Storage at
`storage/generated/loopino-phase1-browser-2026-10-15/`, with official metadata,
image dimensions and SHA-256 verification.
