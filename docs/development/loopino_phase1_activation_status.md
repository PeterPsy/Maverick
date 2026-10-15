# Loopino phase 1 server activation checkpoint

2026-10-15. The installation in `/root/projects/loopino` has completed its native
address job, Cloudflare connection and AI provider activation. This supersedes
the pending server-setup gates in the historical deployment and relocation
reports. Phase 1 remains open for authenticated visual acceptance, signed Apple
clients and native hardware acceptance; Mac configuration remains last.

## Address and setup

Job `3f01adc147b746bc916a9134c1522066` is `ready`. The canonical address is
`https://loopino.giuntitrail.com`, using Cloudflare secret reference
`platform:secrets/cloudflare-dns`. The main hostname, app-frame hostname and
sidecar hostname passed HTTPS verification. The wildcard certificate is issued,
the real renewal dry run passed, and the installation timer is active.

The observed setup loop occurred while the initial job was still preparing DNS,
certificates and renewal. After activation, `configured=true` and
`setup_required=false`; authenticated public requests to `/` and `/app/chat`
returned 200 without a setup redirect. No setup gate was bypassed or disabled.

## Providers

The user explicitly authorized reusing the Codex and Antigravity logins already
present on this server. Only their required identity files were adopted into
the installation-owned private provider sources, with service ownership and 0600
permissions. No root configuration, rules or business data was copied.

Codex 0.162.1 remains the default with `gpt-6.1-sol`. Antigravity 1.3.4 is installed
at the protected `.toolchains/bin/agy`, matching the reviewed SHA-256
`5b93565c5f04ea4f7b79d49d5c3237449bf6ce47b6779e8cf46c1fae97957c98`.
The pre-existing root CLI remains unchanged. Its authenticated catalog exposed
Gemini 3.8 Flash, Claude Sonnet 4.6, Claude Opus 4.6 Thinking and GPT OSS 120B.
All four were registered during activation. The final workspace selection keeps
Gemini enabled; the other three were explicitly disabled afterward and those
choices survived the verification restart. Codex remains the default. The two
documented Antigravity runtime switches are enabled; no fake-data declaration
was issued.

Both engines completed an exact-response sandbox turn and a full-access turn
that called the official read-only `developer-context.list` CLI. Codex's CLI
call succeeded directly. Antigravity's native tool reported one failed attempt,
then completed the same command and final response successfully. The redacted
receipt preserves this retry rather than claiming a first-attempt pass.
Temporary smoke conversations were cleaned through the official thread API.

## Full-access host administration

A subsequent operator request aligned host privileges with the source
installation. The source's actual full-access session runs as `ubuntu` (UID
1000) and `sudo -n id -u` returns 0. The destination retains the service account
`loopino` (UID 997), with the equivalent explicit `NOPASSWD: ALL` sudo grant.
The account can administer the whole destination host through `sudo -n`,
including protected files, services, packages, containers and firewall rules.
Direct file operations still use the service account's Linux permissions.

The protected rule and its exact OS registration are documented in
[installation architecture](../architecture/installation_address.md#operator-host-access-for-this-installation).
The rule is effective for existing full-access processes immediately; Core's
service identity and the runtime-mode policy are unchanged.

Live verification passed candidate and complete sudoers validation, root UID
execution, Docker/firewall/journal reads, and creation/read/removal of a
root-owned marker inside the private installation operations tree. Real Codex
and Antigravity full-access chats each ran `id -u` and `sudo -n id -u`, returned
997 and 0, and completed the expected final response. Codex succeeded directly;
Antigravity reported one failed tool attempt before each successful command.
These temporary chats were removed through the official thread API afterward.

The non-default workspace policy still resolves an explicit full-access request
to sandbox. A real Bubblewrap launch as `loopino`, with sudo and its runtime
libraries available, retained `NoNewPrivs: 1`: sudo explicitly refused elevation,
and the host sudoers rule and private operations path were absent. The root-owned
private receipt is `operations/phase1/host-access/verification.json`, alongside
`sudo-policy.json` and the temporary session identifiers. This was an OS
configuration change; no Core/provider source, user chat or frontend was modified.

## Corrections and verification

- `1725e212`: resolve native Codex binaries in nested and hoisted npm layouts;
  traverse private workspace ancestors with no-follow path descriptors while
  retaining read authority only at the final workspace. Root ACLs were preserved.
- `5a4b3ce5`: use the valid `loopino-test` development/test password consistently
  in Core fallback, the test runner and shared test defaults.
- Focused checks: 167 runtime-tool tests, 12 Codex launch/resolution tests,
  one development credential regression and two identity CLI tests passed.
  The initial broad invocation lacked test PATH prerequisites and used deployment
  environment values; the isolated test environment with protected Bubblewrap
  and ripgrep paths passed all 167 cases.
- Unused-import and diff-whitespace checks passed.
- Authenticated inventory lists all 26 standard apps. Core, Browser, OpenWA and
  the installation timer are active. No app source or frontend artifact changed.

Private operational evidence is under `operations/phase1/providers`, including
`verification.json`, `smoke-checks.json` and `runtime-tools-tests.log`. Credentials
and operational files remain outside source commits. This checkpoint does not
perform predecessor data migration or configure the Mac.
