# Governance

Maverick v3 is currently maintainer-led.

## Maintainer Authority

Maintainers are responsible for:

- accepting or rejecting changes
- defining release scope
- enforcing architecture boundaries
- coordinating security response
- deciding whether a change belongs in core, an app, or documentation

## Decision Standard

When multiple implementations are valid, prefer the one that is:

1. easier to read
2. easier to test
3. easier to delete or change later
4. more consistent with `docs/architecture/`

## Architecture Changes

Architecture decisions belong in `docs/architecture/` or a future ADR. Code that changes architecture without updating docs should not be merged.

## Security Decisions

Security embargoes, disclosure timing, and vulnerability severity are maintainer decisions until a formal security team exists.

## Release Authority

Only maintainers may cut releases. Public release is blocked until the P0 checklist in `OPEN_SOURCE.md` is complete.

## Contributor Roles

The project does not yet have formal reviewer, triager, or release-manager roles. Add those roles before broad public announcement.
