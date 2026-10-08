# General Device Use efficiency — 2026-10-08

Core commits `9e860d1c` and `50ca1ffe` are published on `design`. Native commit
`975c0cea1944e19d0f28a4b495ccff0d29ee4505` is published on
`giuntiocram/maverick-glasses-ios`, `maverick-integration`.

The paired contract is `macos-v50`, digest
`4dd7bf89e6dd520294199f7b997e9388debf6004aaa6f618715033b77ed4b238`.
All changes apply to declared platform capabilities rather than a particular
editor, project, source filename or subtitle style.

## Delivered behavior

- Speech file transcription can request measured word intervals from Deepgram or
  faster-whisper and prepare captions/SRT in that same call. Pure subtitle
  preparation is available through backend, CLI and MCP. Grouping accepts word,
  character, duration, pause and offset limits; missing word timing is explicit
  and never repaired by inventing boundaries. Worker timing flags are per job;
  the private worker protocol and backend dependency fingerprints prevent reuse
  of an older daemon that cannot implement the new request.
- Native project media can generate SRT from measured words or existing captions,
  and on-device transcription can optionally prepare SRT. Direct primitives use
  the same pre-write validation as declarative scripts. Source immutability and
  generated-path confinement remain mandatory.
- Compact Peekaboo images cap the longest side at 1600 pixels and default text
  at 3500 characters. Explicit detail/size controls retain access to small UI
  controls. The preview uses the exact delivered JPEG; normalized pointer
  coordinates still map onto the original captured window.
- Classified uncertain input can return a fresh same-window observation through
  `observe_after`, preserving the original outcome without replay or a claim of
  effect. Refused, partial, unclassified and failed-capture cases keep recovery
  handling. Agents reuse fresh observations and prefer declared structured
  operations/bulk import over repetitive gestures.
- `core.runtime.usage.read` exposes authoritative chat/turn consumption, cached
  input and active context through transcript authorization. Numeric aliases
  preserve credential redaction. Device Use audit includes usage, uncertainty,
  image-acknowledgement latency and result text size with historical coverage.
  Missing measurements remain null; outside-bridge time is not model time.

## Verified rollout

Backend restart changed PID `1016581` to `1048813`; the existing
`maverick-core.service` is active/running and `/health` returned
`{"status":"ok","service":"maverick-core"}`. The ordinary restart command could
not reach systemd in its mount namespace; the existing host-namespace systemctl
route completed the authorized restart. The managed process uses SQLite 3.51.3.

Native build [37767982922](https://github.com/giuntiocram/maverick-glasses-ios/actions/runs/37767982922)
passed 283 Swift tests, signed background-input acceptance, release compilation
and signing checks. Installation
[37769661264](https://github.com/giuntiocram/maverick-glasses-ios/actions/runs/37769661264)
repeated those checks at the exact native commit, verified identity continuity
and atomic update at the existing path, and reported
`Installed and running: 0.2.3 (54)`.

Focused verification passed 135 Speech tests, 52 Core diagnostics/device/provider
tests and 18 reconnection tests. The 52 checks also passed with the managed
backend's SQLite environment. Unused-import and diff checks passed. Live CLI and
MCP calls returned matching usage counts and valid grouped SRT; live audit and
direct-turn usage reads succeeded.

The broad fast suite was not green: six unrelated unit failures were reproduced
on an isolated unchanged checkout, along with three existing shell assertions.
It also reported a concurrently modified sidebar assertion, a Design Studio
update-handoff assertion, and Storage/Senses tests whose unconfigured Python
loaded SQLite 3.46.1 rather than the managed backend library. The audit regression
found during this work was corrected and the focused suite rerun successfully.
This rollout does not claim a green global suite.

## Baseline and next measurement

The authorized diagnostic chat
`7a024b8e-d73b-4c14-b614-880f93693925` has exact Core Usage coverage with 123
samples: 10,346,400 processed units, including 9,668,736 cached input, 652,953
uncached input, 12,738 output and 11,973 reasoning output. Non-cached consumption
is 677,664. Estimated monetary cost is unavailable; these counts are not a bill.
The historical audit contains 128 native calls across four turns. Provider
image-delivery latency was not recorded then and remains unavailable.

An existing PC Use chat must explicitly reconnect to adopt the reviewed v50
lease and fresh provider context. The installed build and controlled native
acceptance are verified; the next real editing workflow supplies the performance
comparison. Use the same authorized source, timeline, model/profile and quality
requirements, then compare elapsed time, calls, uncertainties, images/text,
non-cached consumption and context through the new diagnostic surfaces. Review
actual caption coverage and alignment before accepting a bulk import. Constant
offsets do not account for cuts, reordered clips or speed changes. No percentage
speedup or token-saving result is claimed without that comparison.
