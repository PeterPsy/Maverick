# Video Studio Supply-Chain Baseline

This directory is the reviewable development baseline for Video Studio's Node
and media toolchain. It is not signed release provenance, a vulnerability
attestation, legal advice, or permission to redistribute native media binaries.

## Reproduce and verify

Use Node.js 24 (`>=24.11.0 <25`) and npm `11.6.1`:

```bash
npm ci
npm run check:supply-chain
npm run check:ffmpeg
npm run check:vulnerabilities
npm run compliance:generate
npm test
```

`compliance:generate` is offline after `npm ci`; it rebuilds the CycloneDX
baseline, notices, and provenance from the lockfile, policy, committed
compositor inventory, installed Remotion license, and FFmpeg host manifest.
Regeneration is deterministic for the fixed policy snapshot.

The model inventory is empty by design. A future model is rejected unless it
has an immutable revision, distinct code and weights licenses, a model card,
tokenizer version, and SHA-256 digests for every installed artifact.

Refreshing the compositor inventory is an explicit networked review action:

```bash
npm run compliance:inventory-compositors
```

It downloads only the seven tarballs resolved by `package-lock.json`, verifies
their npm SHA-512 integrity, safely inspects the package roots, records archive
and embedded-file SHA-256 digests, and captures the executable Linux x64 GNU
FFmpeg build flags. Review the resulting diff; never treat regeneration as
automatic license acceptance.

## Release boundary

The local development tree includes `@remotion/renderer`, whose optional native
compositor packages have `NOASSERTION` license metadata and embed FFmpeg,
ffprobe, native Remotion executables, and media libraries. The inspected Linux
x64 GNU build is GPL-enabled and includes libfdk-aac, libx264, and libx265.

Any release, bundle, installer, appliance, worker, image, or container must run:

```bash
npm run check:release-artifact -- <artifact-path>
```

The check recursively inspects directories and nested tar/ZIP payloads. It
fails on compositor paths, FFmpeg/ffprobe payloads, unsafe archives, inspection
errors, or excessive nesting. This block remains until later ADRs and legal
review define redistribution, corresponding source, build scripts, patches,
notices, codec/patent policy, signatures, and updates.

The operator-installed `/usr/bin/ffmpeg` and `/usr/bin/ffprobe` form a separate
host capability governed by ADR-0008. The verifier accepts only manifest-bound
absolute paths, checks both binary digests and complete build flags, uses argv
arrays with no shell, and fails closed without PATH fallback.
