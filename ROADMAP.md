# Roadmap

Maverick v3 is pre-release software. This roadmap is intentionally conservative and security-first.

## Done

- root legal, contributor, and community files
- baseline CI and secret scanning
- first public release checklist
- developer-context CLI and MCP surfaces for workspace agents
- ADR seed set and public threat model

## In Progress

- Complete the first public release checklist from `OPEN_SOURCE_CHECKLIST.md`.
- Keep non-default workspace runtime sessions sandbox-first.
- Keep architecture docs, ADRs, and implementation aligned.
- Keep the CLI-first local setup path reproducible from a clean clone.

## Planned

- Close security blockers from `SECURITY_AUDIT.md`.
- Add public docs index, glossary, and app developer tutorial.
- Add stronger dependency audit, SBOM generation, and release checks.
- Add browser smoke tests for core shell and mounted apps.

## Later

- Add a built-in setup or onboarding UI after the CLI-first setup path stabilizes.
- Add production deployment guide after security blockers are closed.
- Add third-party app trust profiles.
- Add release provenance and signed artifacts.

## Help Wanted

- security hardening that closes documented launch blockers
- docs improvements that reduce contributor onboarding time
- browser and accessibility coverage for built-in apps
- release and provenance automation

## Not Planned

- Maverick v2 compatibility shims.
- Treating app internals as core platform APIs.
- Marketing Maverick as production-ready before the security roadmap is complete.
