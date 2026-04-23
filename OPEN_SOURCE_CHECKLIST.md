# Open Source First Release Checklist

Date: 2026-04-23

## Purpose

This checklist turns the broader audit in `OPEN_SOURCE.md` into an execution plan for Maverick's first public open source release.

It is optimized for:

- getting Maverick public soon
- being honest about the current maturity level
- making local setup easy enough for external reviewers
- deferring installer/setup UI work until the repository, docs, and security messaging are in better shape

This checklist assumes the first public position is:

- open source
- experimental
- self-hostable
- not production-ready

## Release Goal

The immediate goal is not "production credibility."

The immediate goal is:

- a serious public repository
- clear local setup
- clear security limitations
- clean architecture messaging
- enough contributor documentation that external reviewers do not bounce off immediately

## Execution Order

1. Public positioning and release message
2. Local setup path
3. Security posture and threat model
4. Architecture explanation and ADRs
5. API, provider, and persistence docs
6. Supply-chain and repository hygiene
7. Contributor-facing docs and roadmap polish
8. Public deployment docs
9. Final release review
10. Installer/setup UI as the last item of the phase

## Block 1: Public Positioning And Release Message

- [ ] Fix the public project position:
  - open source
  - experimental
  - self-hostable
  - not production-ready
- [ ] Align `README.md`, `SECURITY.md`, `OPEN_SOURCE.md`, and `ROADMAP.md` with the same message.
- [ ] Verify that no document implies Maverick is already production-safe.
- [ ] Add or refine a short "What Maverick is" section.
- [ ] Add or refine a short "What Maverick is not" section.
- [ ] Add or refine a "Current limitations" section.
- [ ] Define one short public launch description that can be reused in the announcement.

Exit criteria:

- an external reader can understand the current maturity level in under a minute
- the repository does not overclaim security or readiness

## Block 2: Local Setup Path

- [ ] Choose one recommended setup path and make it the default public path.
- [ ] Minimize the number of steps in the README setup instructions.
- [ ] Document exact prerequisites:
  - Python
  - Node
  - MongoDB
  - Linux and bubblewrap expectations
  - Codex requirement where relevant
- [ ] Add or consolidate simple scripts for:
  - bootstrap dependencies
  - run locally
  - run core checks
- [ ] Verify a fresh-clone setup using only public documentation.
- [ ] Remove dependence on hidden machine-local paths or already-running private services.
- [ ] Clarify what features work without provider setup and which ones require provider configuration.

Exit criteria:

- a new external user can get Maverick running locally from a clean clone without private context

## Block 3: Security Posture And Threat Model

- [ ] Review `SECURITY_AUDIT.md` and separate:
  - known risks
  - existing mitigations
  - production blockers
- [ ] Add `docs/security/threat_model.md`.
- [ ] Define the core trust boundaries clearly:
  - browser user
  - workspace user
  - app frontend
  - app backend
  - runtime agent
  - provider subprocess
  - platform core
  - local host
  - external providers
- [ ] Surface the most important security limitations in the README.
- [ ] Verify that `SECURITY.md` points to the correct disclosure and reporting path.
- [ ] Verify that no document contradicts the actual security posture.

Exit criteria:

- a security-aware reviewer can understand the threat boundaries and the current non-goals
- the public docs are honest about the current risk level

## Block 4: Architecture Explanation And ADRs

- [ ] Create `docs/adr/`.
- [ ] Add ADRs for at least:
  - workspace isolation
  - app contract model
  - runtime provider abstraction
  - committed dist policy
  - secret storage model
  - licensing choice
- [ ] Verify that ADRs and architecture docs do not contradict each other.
- [ ] Add a short docs map in the README describing where to start reading.
- [ ] Reduce the risk that a new contributor gets lost in long architecture documents.

Exit criteria:

- an external contributor can understand the main design decisions without reading the entire architecture set first

## Block 5: API, Provider, And Persistence Documentation

- [ ] Add a minimal public reference for the main core-facing APIs and capability surfaces.
- [ ] Document the provider model more clearly:
  - runtime provider role
  - Codex assumptions
  - sandbox and full-access implications
  - environment requirements
- [ ] Document persistence more clearly:
  - MongoDB role
  - control-plane vs app-owned data
  - what lives under `workspaces/`
- [ ] Mark what is stable vs still evolving.

Exit criteria:

- a technical reviewer can understand how the system is supposed to be used and extended

## Block 6: Supply Chain And Repository Hygiene

- [ ] Complete the declared Python dependency story.
- [ ] Verify lockfiles and npm package consistency for all relevant apps.
- [ ] Add or complete a third-party dependency inventory or SBOM.
- [ ] Strengthen dependency and secret-scanning checks.
- [ ] Verify CI coverage for:
  - Python tests
  - compileall
  - unused import checks
  - relevant frontend builds
  - secret scan
- [ ] Re-run repository hygiene checks for:
  - local state
  - generated junk
  - private paths
  - private hostnames
  - leftover secrets

Exit criteria:

- an external reviewer can see a credible supply-chain and repository hygiene story

## Block 7: Contributor-Facing Docs And Roadmap Polish

- [ ] Refine `CONTRIBUTING.md` for external contributors.
- [ ] Make sure contributors can tell how to:
  - work on the core
  - work on apps
  - improve docs
  - report issues
- [ ] Refine `ROADMAP.md` as a public roadmap rather than an internal task dump.
- [ ] Make sure roadmap sections clearly distinguish:
  - done
  - in progress
  - planned
  - not planned
  - help wanted
- [ ] Verify `.github` templates and labels match the actual contribution flow.

Exit criteria:

- contributors can find work and understand how to participate without private context

## Block 8: Public Deployment Docs

- [ ] Make deployment docs generic and public-facing.
- [ ] Clarify the difference between:
  - local development
  - self-hosted testing
  - unsupported production use
- [ ] Avoid implying that current deployment docs are a production endorsement if they are not.
- [ ] Provide at least one credible path for running Maverick outside the maintainer machine.

Exit criteria:

- a serious reader can understand how to self-host for evaluation without mistaking it for production guidance

## Block 9: Final Release Review

- [ ] Run a root-level documentation review.
- [ ] Run a final fresh-clone setup review.
- [ ] Run CI on a clean branch state.
- [ ] Run a final secret scan.
- [ ] Re-check the repo for private hostnames, private paths, and accidental internal material.
- [ ] Decide the wording for the public launch announcement.
- [ ] Open public follow-up issues for anything intentionally deferred.

Exit criteria:

- the repository is coherent enough for a first public release
- the known gaps are visible and tracked rather than hidden

## Final Item Of The Phase: Installer / Setup UI

This is intentionally last.

- [ ] Design a built-in `Setup`, `Onboarding`, or `First Run` app flow.
- [ ] Keep it as post-bootstrap guidance, not the first bootstrap mechanism.
- [ ] Make it show:
  - system status
  - prerequisites
  - provider readiness
  - workspace readiness
  - security warnings
- [ ] Implement it only after the CLI-first setup path is stable and documented.

Exit criteria:

- the setup UI improves onboarding without encoding a moving bootstrap target too early

## Release Gate

Maverick is ready for the first public open source release when:

- public positioning is clear and honest
- local setup is verified from a fresh clone
- threat model exists
- minimum ADR set exists
- API/provider/persistence docs are understandable
- supply-chain and secret-scanning story is credible
- contributor docs are usable
- deployment docs are public-facing and honest
- installer/setup UI remains explicitly deferred unless the earlier blocks are stable
