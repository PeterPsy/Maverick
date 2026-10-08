# macOS external links repair — 2026-10-08

Shell commit: `975e1327` (`design`, pushed).
Native implementation: `abeae97`; test-fixture correction: `286380e`
(`maverick-integration`, pushed).
Installed native source revision: `286380ef004f32f0025fd8e4bc990071b67cb400`.

The Storage sidebar account button opens `about:blank` before awaiting its OAuth
URL. MaverickMac had no `WKUIDelegate` to create that receiver, and its main-frame
navigation policy cancelled every external destination while clearing Device Use.
Those two native behaviors explain the difference from the working browser UI.

External HTTP(S) navigation now opens the default system browser. The shell's
existing validated app/widget broker first uses a platform-main-frame-only
`maverickExternalURL` handler, avoiding a duplicate launch from the null return of
`noopener` followed by browser fallback. Native WebKit also handles blank-target
links, clicked iframe links and the asynchronous Storage popup. Receivers have no
native handlers, never load external documents and are released after handoff or
cancellation. Internal app navigation remains embedded, and external handoff
does not clear Device Use. The wire contract remains v51; no Core restart was
needed.

Validation:

- All 250 shell frontend tests passed. The official frontend build succeeded and
  published the runtime refresh event; rebuilt distribution assets are committed.
- The Mac Python script suite ran 44 tests, with one signing case skipped on Linux.
- Mac build run
  [`37797766466`](https://github.com/giuntiocram/maverick-glasses-ios/actions/runs/37797766466)
  passed all 297 Swift tests, including five external-navigation tests, and all
  16 signed native cases.
- Explicit installation run
  [`37798246569`](https://github.com/giuntiocram/maverick-glasses-ios/actions/runs/37798246569)
  repeated those checks, verified code identity continuity, updated the existing
  app path and confirmed `Installed and running: 0.2.6 (57)` at 15:10:02 UTC.
- Unused-import and diff checks passed.

The broader shell Python fast suite reports four existing source-string assertion
failures in app mounting/sidebar checks outside this change (70 tests, 54 skipped).
The relevant implementation and test files were unchanged by this repair.

The real WebKit regression tests capture the system-opener effect; they verify
the destination and exactly one handoff while preserving the shell. They do not
complete a live Google consent flow or change account connections. OAuth remains
in the system browser's session and uses the existing authenticated Maverick
callback; native cookies are never transferred.
