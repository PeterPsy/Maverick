# ADR-0008: Video Studio FFmpeg Build And Distribution

## Status

Accepted on 2026-08-06 and amended on 2026-08-08 for the current local server
in Video Studio phases 1 through 3.

## Context

Video Studio needs FFmpeg and ffprobe for media inspection, derivatives, audio
analysis, H.264 encoding, and output validation. FFmpeg is primarily LGPL
2.1-or-later, but enabling its optional GPL components changes the resulting
FFmpeg build to GPL 2-or-later.

The current server provides the Ubuntu package `ffmpeg
7:7.1.1-1ubuntu1.3`. Its `ffmpeg -buildconf` output includes `--enable-gpl`,
`--enable-libx264`, and `--enable-libx265`. The executable observed at
`/usr/bin/ffmpeg` on 2026-08-06 had SHA-256
`8ad7731105142fb4e70dbccf4fd25e4df71e448001dee6f5167ce0d3e961aeac`.
This hash records the audited local baseline; it is not permission to accept an
unreviewed replacement at the same path.

The corresponding `/usr/bin/ffprobe` SHA-256 is
`96b609cc3ad9f2f6a4e505bd3e8bc3785822dc609a1e4947ddff0db7b313e69e`.
Both identities and the complete build configuration are committed in the
machine-readable Video Studio host manifest.

## Decision

For phases 1 through 3, Video Studio uses the current GPL-enabled Ubuntu FFmpeg
as a governed external process on the local server. It is not imported, linked,
embedded, vendored, copied into the repository, or executed inside the Video
Studio Python or Node process. The app invokes a validated executable with an
argument array through the durable job executor; it never constructs a shell
command string.

The current local H.264 server preset uses `libx264`. This decision authorizes
that codec only for the governed local server profile described here. It does
not authorize Maverick or Video Studio to sell, sublicense, or redistribute the
FFmpeg binary, an FFmpeg-containing image, or another compiled FFmpeg artifact
as part of the app.

This accepted host capability does not cover the FFmpeg/ffprobe executables and
libraries embedded in Remotion's optional compositor packages. Those binaries
have distinct digests and build configurations; the inspected Linux x64 GNU
variant additionally enables `libfdk-aac`. They are inventoried as an unresolved
local-development dependency under ADR-0007 and are forbidden in release,
bundle, installer, image, and container artifacts. Runtime reports must never
attribute compositor media work to this host manifest.

Each accepted FFmpeg installation has a content-addressed build manifest. At
minimum it records:

- absolute executable identity resolved by the trusted executor, without
  exposing the host path to users or agents;
- package/source provenance and architecture;
- `ffmpeg -version`, `ffprobe -version`, and complete `ffmpeg -buildconf`
  output;
- SHA-256 digests of the `ffmpeg` and `ffprobe` executables or immutable image
  digest;
- enabled GPL/non-free flags and relevant external codec libraries;
- the tested codec, container, filter, hardware-acceleration, and pixel-format
  allowlists;
- manifest schema version, review date, reviewer, and applicable notices.

Every render report records the FFmpeg build-manifest digest, requested and
observed codec/container, effective encoder, relevant encoding parameters, and
quality-gate result. A worker whose actual binary or build configuration does
not match an accepted manifest is incompatible and must fail closed before it
processes media.

The verifier invokes only the manifest's absolute `ffmpeg` and `ffprobe` paths
using argument arrays with `shell: false` and an allowlisted environment. It
checks the real path, executable SHA-256, exact first version line, complete
ordered build configuration, GPL classification, required legal flags, sandbox
contract, and non-empty codec/container/pixel-format allowlists. A missing or
malformed manifest is a capability denial rather than a PATH fallback.

FFmpeg and ffprobe run inside the job sandbox with granted inputs mounted
read-only, a dedicated writable staging directory, an allowlisted environment,
no default network egress, resource limits, timeout, and whole-process-tree
termination. The worker promotes no output until technical validation and
Storage reconciliation succeed.

## Distribution Boundary

The repository may contain code that invokes FFmpeg and documentation of the
required server capability. It does not contain or publish the FFmpeg binary.
An operator installs the audited Ubuntu package independently on the local
server.

Any future release, installer, appliance, container, VM image, or downloadable
worker artifact that includes FFmpeg crosses this boundary and is blocked until
a new ADR and legal review define at least:

- the exact source and binary artifacts being conveyed;
- complete corresponding source, build scripts, patches, notices, and license
  delivery required by the selected GPL/LGPL build;
- codec and patent policy for every target jurisdiction and distribution
  channel;
- SBOM, vulnerability scan, signatures, checksums, provenance, and update
  process;
- whether the surrounding aggregation and delivery method preserve Maverick's
  intended licensing.

The fact that Video Studio invokes FFmpeg as a separate process is not used as
a substitute for complying with obligations that arise when an FFmpeg binary
or image is distributed.

## Future LGPL-Only Profile

An LGPL-only reproducible FFmpeg build is a permitted future alternative, not
part of this decision. It must omit `--enable-gpl` and other incompatible
components, define how required codecs including H.264 are provided, pass the
full media/render/quality suite, and receive its own ADR and accepted build
manifest before use. Switching builds must not occur silently through `PATH` or
an operating-system update.

## Verification And Release Gates

- The executor must compare executable or image digests and complete build
  identity with an accepted manifest before leasing compatible jobs.
- Tests must prove array-based invocation, metacharacter-safe arguments,
  sandboxed filesystem access, deny-by-default egress, bounded resources,
  timeout, cancellation, and termination of stubborn descendants.
- Compatibility tests must cover ffprobe parsing and every advertised
  container/codec preset, including local H.264 through `libx264`.
- Render reports and output provenance must reference the accepted manifest by
  digest rather than only recording the string `ffmpeg`.
- The release SBOM and Third-Party Notices must describe the external FFmpeg
  requirement and the audited build license accurately.
- A binary/image distribution gate must fail whenever an FFmpeg artifact is
  found in an app or release bundle without the later distribution ADR and its
  required compliance artifacts.
- The distribution gate must also reject Remotion compositor directories and
  nested archive/container layers containing `ffmpeg` or `ffprobe`; inspection
  errors and unsafe archive entries fail closed.
- A package upgrade, checksum change, build-configuration change, codec change,
  or new target architecture requires compatibility, vulnerability, and
  license review before acceptance.

## Consequences

- Phase 1 can provide H.264 on the current server without embedding FFmpeg into
  Video Studio source or process space.
- The selected local build is GPL 2-or-later and must be reported as such; it
  must not be mislabeled as LGPL merely because FFmpeg's default build is LGPL.
- Render provenance is tied to a concrete media toolchain and remains auditable
  after server changes.
- Shipping a self-contained worker or container remains blocked until its
  distribution and codec obligations are explicitly resolved.
- A later LGPL-only profile remains possible without changing the Project IR or
  job protocol.

## Primary Sources

- [FFmpeg license](https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md)
- [FFmpeg legal and compliance checklist](https://ffmpeg.org/legal.html)
- [Ubuntu source package `ffmpeg 7:7.1.1-1ubuntu1.3`](https://launchpad.net/ubuntu/+source/ffmpeg/7%3A7.1.1-1ubuntu1.3)
- [x264 license](https://code.videolan.org/videolan/x264/-/blob/master/COPYING)
- [Remotion renderer optional compositor declarations at v4.0.506](https://github.com/remotion-dev/remotion/blob/v4.0.506/packages/renderer/package.json)
