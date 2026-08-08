# ADR-0007: Video Studio Remotion 4 License And Version

## Status

Accepted on 2026-08-06 for Video Studio phases 1 through 3.

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
- The dependency tree must not contain `@remotion/transitions`.
- Preview/render golden tests and a server render compatibility test must pass
  before changing any approved package.
- Third-Party Notices must reproduce the applicable Remotion License and all
  required permissive-license notices without suggesting that Remotion is
  covered by Maverick's MIT license.

## Consequences

- Builds are reproducible with respect to the selected Remotion release.
- Remotion upgrades are deliberate release events rather than routine range
  resolution.
- Video Studio can provide transitions without accepting the unresolved
  `@remotion/transitions` package metadata.
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
- [OpenChatCut AGPL-3.0 license](https://github.com/0xsline/OpenChatCut/blob/main/LICENSE)
- [OpenMontage AGPL-3.0 license](https://github.com/calesthio/OpenMontage/blob/main/LICENSE)
- [Essentia AGPL-3.0 license](https://github.com/MTG/essentia/blob/master/COPYING.txt)
