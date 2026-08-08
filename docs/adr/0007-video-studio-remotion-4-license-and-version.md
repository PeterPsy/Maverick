# ADR-0007: Video Studio Remotion 4 License And Version

## Status

Accepted on 2026-08-06 and amended on 2026-08-08 for Video Studio phases 1
through 3.

## Context

Video Studio uses Remotion as its preview and server-rendering engine. Remotion
uses a project-specific license rather than the repository's MIT license, and
its npm packages must remain version-aligned. The legal eligibility and exact
dependency set therefore need an explicit, reviewable decision before the app
can render or ship release artifacts.

The project owner has declared that Maverick and Video Studio are currently a
personal project used and developed by an individual. This declaration is the
basis for the Remotion Free License decision below; it is not a general legal
conclusion for future owners, organizations, services, or distribution models.

The npm registry reported `4.0.506` as the stable `latest` version for the
selected Remotion packages on 2026-08-06. The `@remotion/transitions` package
instead declares `UNLICENSED`, and its published tarball does not contain a
license file.

The published `@remotion/renderer@4.0.506` dependency tree also declares seven
platform-specific compositor packages as optional dependencies. Their package
metadata and npm tarballs do not contain an adequate license declaration. Each
tarball embeds FFmpeg, ffprobe, native Remotion code, and media libraries. The
audited Linux x64 GNU FFmpeg executable reports `--enable-gpl`,
`--enable-libfdk-aac`, `--enable-libx264`, and `--enable-libx265`. This is a
material redistribution risk, not ordinary missing npm metadata.

## Decision

Video Studio phases 1 through 3 pin these packages to the exact version shown,
without `^`, `~`, npm aliases, or mixed Remotion versions:

| Package | Exact version | License basis |
|---|---:|---|
| `remotion` | `4.0.506` | Remotion License |
| `@remotion/player` | `4.0.506` | Remotion License |
| `@remotion/renderer` | `4.0.506` | Remotion License |
| `@remotion/bundler` | `4.0.506` | Remotion License |
| `@remotion/captions` | `4.0.506` | MIT |

`@remotion/transitions` is excluded. Video Studio may implement allowlisted
transition behavior with the approved Remotion primitives and Maverick-owned
code, but it must not install, copy, vendor, or derive code from
`@remotion/transitions` until its license is clarified in writing and a later
ADR accepts the result.

The individual owner is treated as eligible for the Remotion 4 Free License for
the declared personal use. Remotion code is consumed through published
packages, remains under its own license, and is not copied into or relicensed as
Maverick MIT source. Video Studio must not copy or modify Remotion for the
purpose of selling, renting, licensing, relicensing, or sublicensing a
derivative of Remotion.

Remotion 5 and later major versions are outside phases 1 through 3. They require
a new ADR, license review, migration plan, exact dependency inventory, and full
preview/render compatibility suite before adoption.

OpenChatCut, OpenMontage, Essentia, and other AGPL sources are reference-only.
The team may study public product behavior and general concepts, but Video
Studio implementation must be clean-room Maverick-native work. No source,
assets, fixtures, schemas, or non-trivial expression from those repositories
may be copied or adapted without a separate explicit licensing decision.

### Native compositor development exception

The seven exact `4.0.506` compositor tarballs may be installed from the
integrity-pinned npm lockfile for the declared individual's local development
and compatibility testing only. This is a narrow, visible risk acceptance for
the development baseline; it is not a conclusion that the tarballs or their
embedded binaries are redistributable, and it does not silently relabel their
missing license metadata.

The complete package archive and embedded-file digests are recorded in
`apps/video-studio/compliance/remotion-compositor-inventory.json`. The inventory
is regenerated from the lockfile-resolved tarballs and verifies npm SHA-512
integrity before inspection. Any archive, integrity, embedded-file set, build
flag, version, or license-metadata change invalidates this exception.

Release, bundle, installer, appliance, worker image, VM image, and container
artifacts must exclude all compositor packages and their FFmpeg/ffprobe/native
payload until a later ADR and legal review govern redistribution, corresponding
source, build scripts, patches, notices, codecs, and update obligations. The
separate release-artifact gate enforces this boundary and inspects nested tar
and ZIP payloads fail closed.

## Mandatory Re-Review Triggers

The Remotion decision must be reviewed before any of the following:

- ownership or development moves from the declared individual to another legal
  entity;
- an eligible organization grows beyond the threshold in the applicable
  Remotion license;
- Video Studio becomes a customer-facing or third-party service under a changed
  legal or commercial use model;
- Video Studio or a Remotion-based editor is sold, rented, licensed,
  relicensed, or sublicensed;
- Remotion code is modified or redistributed rather than consumed as an
  independently licensed dependency;
- any Remotion package changes version, license metadata, integrity, or
  distribution terms;
- `@remotion/transitions` or another currently excluded package is proposed;
- Remotion 5 or another major version is proposed.

When a trigger occurs, release and deployment remain blocked until the new ADR
records the subject using the software, intended use, applicable version,
license text, dependency inventory, and review date.

## Verification And Release Gates

- `package.json` and `package-lock.json` must contain the exact approved
  versions for every direct Remotion dependency.
- An automated test must fail when any installed `remotion` or
  `@remotion/*` package has a different version.
- The lockfile integrity and complete transitive tree, including native
  compositor packages selected for the target platform, must be captured in
  the release SBOM.
- The license gate must fail on `UNKNOWN`, `UNLICENSED`, AGPL, GPL, or another
  unapproved license. Exceptions require a specific ADR; they cannot be
  allowlisted silently.
- The only current `NOASSERTION` exception is the exact compositor development
  inventory above; it has `redistribution_allowed: false` and may never make a
  release gate pass.
- The dependency tree must not contain `@remotion/transitions`.
- Preview/render golden tests and a server render compatibility test must pass
  before changing any approved package.
- Third-Party Notices must reproduce the applicable Remotion License and all
  required permissive-license notices without suggesting that Remotion is
  covered by Maverick's MIT license.
- The committed CycloneDX SBOM, notices, and provenance are a regenerable
  development baseline. They must state that they are neither final legal
  approval nor signed release provenance while redistribution is blocked.

## Consequences

- Builds are reproducible with respect to the selected Remotion release.
- Remotion upgrades are deliberate release events rather than routine range
  resolution.
- Video Studio can provide transitions without accepting the unresolved
  `@remotion/transitions` package metadata.
- Local renderer compatibility can be developed without concealing the native
  compositor risk; self-contained distribution remains blocked.
- The current decision supports the declared personal project but does not
  authorize a future company, hosted product, sale, or relicensing model.
- Clean-room provenance review is part of the release gate for work inspired by
  AGPL reference projects.

## Primary Sources

- [Remotion License at v4.0.506](https://github.com/remotion-dev/remotion/blob/v4.0.506/LICENSE.md)
- [Remotion npm metadata at v4.0.506](https://registry.npmjs.org/remotion/4.0.506)
- [`@remotion/player` npm metadata at v4.0.506](https://registry.npmjs.org/%40remotion%2Fplayer/4.0.506)
- [`@remotion/renderer` npm metadata at v4.0.506](https://registry.npmjs.org/%40remotion%2Frenderer/4.0.506)
- [`@remotion/bundler` npm metadata at v4.0.506](https://registry.npmjs.org/%40remotion%2Fbundler/4.0.506)
- [`@remotion/captions` npm metadata at v4.0.506](https://registry.npmjs.org/%40remotion%2Fcaptions/4.0.506)
- [`@remotion/transitions` package metadata at v4.0.506](https://github.com/remotion-dev/remotion/blob/v4.0.506/packages/transitions/package.json)
- [`@remotion/renderer` package metadata at v4.0.506](https://github.com/remotion-dev/remotion/blob/v4.0.506/packages/renderer/package.json)
- [`@remotion/compositor-linux-x64-gnu` package metadata at v4.0.506](https://github.com/remotion-dev/remotion/blob/v4.0.506/packages/compositor-linux-x64-gnu/package.json)
- [OpenChatCut AGPL-3.0 license](https://github.com/0xsline/OpenChatCut/blob/main/LICENSE)
- [OpenMontage AGPL-3.0 license](https://github.com/calesthio/OpenMontage/blob/main/LICENSE)
- [Essentia AGPL-3.0 license](https://github.com/MTG/essentia/blob/master/COPYING.txt)
