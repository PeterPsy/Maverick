# Supply Chain And Dependency Hygiene

## Purpose

This document explains the current supply-chain posture for the first public Maverick release.

## Current Policy

- root Python dependencies are declared in `pyproject.toml`
- root Python optional extras are declared in `pyproject.toml` and included in the direct dependency inventory
- developer verification dependencies are mirrored in `requirements-dev.txt`
- built-in frontend apps keep per-app `package.json` and `package-lock.json`
- the repository includes GitHub Actions CI and secret-scanning workflows
- the repository includes Dependabot configuration

## Current Limitation

This is not yet a complete provenance story.

For the first release, the goal is:

- explicit dependency declarations
- checked-in npm lockfiles for relevant apps
- direct dependency inventory
- audit tooling present in the repo

Full SBOM generation, signed releases, and stronger provenance are follow-up work.

Video Studio has a narrower app-local development baseline under
`apps/video-studio/compliance/`. It generates a transitive CycloneDX SBOM,
Third-Party Notices, provenance inputs/outputs, a Remotion compositor inventory,
and a content-addressed FFmpeg host manifest. These artifacts intentionally do
not claim final release compliance: native Remotion compositor packages embed
FFmpeg and other libraries without adequate package license metadata, so Video
Studio release, bundle, installer, image, and container artifacts containing
them are blocked by a separate fail-closed gate. See ADR-0007 and ADR-0008.

## Dependency Inventory

Generate the current direct dependency inventory with:

```bash
python3 scripts/generate_dependency_inventory.py
```

This writes:

- `docs/legal/third_party_inventory.json`

That file is a review aid for the first public release. It is not a substitute for a full transitive SBOM.

## Audit Expectations

Before release review:

- run the Python test suite
- run compile and import checks
- run the repository secret scan workflow
- regenerate the dependency inventory if package manifests changed

## Reviewer Guidance

Reviewers should assume:

- lockfiles are authoritative for current frontend dependency resolution
- root Python metadata is authoritative for the main Python package metadata
- stronger release provenance remains planned work rather than completed work
