# Storage downloads and preview repair — 2026-10-13

Storage's download links reached a native host with no WebKit download delegate.
MaverickMac now turns download actions and attachment responses into authenticated
WebKit transfers, presents Save, and keeps the shell and app document mounted.
Exports retain their blob URL during asynchronous handoff. Error responses are
reported rather than saved as the requested file. Completed transfers publish to
the selected destination; cancellation and teardown release pending transfers.
The native implementation is on `maverick-integration`, through `b9de56a`.

The preview also allowed a portrait image's intrinsic height to exceed its grid
row. Media now uses the available box with `object-fit: contain`; the toolbar
remains a separate row. Fullscreen selectors use a forgiving selector list, and
an unconfirmed WebKit fullscreen request falls back to the in-frame layout.
Close is prominent, Download has a desktop label, modal keyboard focus stays
inside, and closing restores the opener. Mobile previews clear the shell header.
File deletion remains available in details and the file list.

Validation:

- All 161 Storage frontend tests passed; TypeScript and the official mounted
  frontend build passed, publishing the frontend refresh event.
- The built frontend passed four Chromium scenarios in sandboxed cross-origin
  frames: native fullscreen, denied fullscreen, 390px and 320px widths. Checks
  include portrait containment, visible controls, mobile header clearance,
  Escape/Close, focus restoration, filenames and exact downloaded bytes.
- MaverickMac's managed macOS build
  [38385740327](https://github.com/giuntiocram/maverick-glasses-ios/actions/runs/38385740327)
  passed script tests, the Swift suite (including real iframe blob downloads,
  overwrite, cancel, teardown and native Save sheet coverage), signed native
  acceptance and release signature checks. Native version is 0.4.3 (77).
- Scoped unused-import and diff checks passed. The broader unused-import check
  reports four existing imports in OpenWA's upstream Python SDK, outside this
  change.
- Storage's Python fast run completed 170 tests with 45 skips and two fixture
  errors. Both widget-mount fixtures copy `core/app_sdk` but omit the
  `core.shared.sqlite_runtime` module imported by the unchanged Storage backend.
  The local interpreter also loads SQLite 3.46.1, below Storage WAL's 3.51.3
  prerequisite. Those fixtures and backend modules were not modified here.

The native workflow above builds and tests without installing. Download support
requires updating the running Mac host to 0.4.3 (77); web changes alone cannot
add the missing native delegate to the existing app.
