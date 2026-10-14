# Loopino phase 1 source provenance and rename decisions

This is a clean installation, not a migration. Installation-owned source,
operational records, toolchains, dependencies, caches and runtime material are
rooted at `/projects/loopino`. Tenant data and provider credentials are created
fresh. The operator's `/root/.codex` login is external development authority only.
No live Nginx/systemd changes, certificate issuance or existing-service changes
belong to tranche 1. Isolated prerequisite/plugin verification stays in-root.

| Source | Baseline commit | Original tree | Destination |
| --- | --- | --- | --- |
| Platform, original `design` | `e76799d05941361e3d896cb2ddcdfbd0517fee3d` | `bf1db4e8c1e26ce0a399f6cadc893d4131e74e91` | `/projects/loopino` |
| Apple, original `maverick-integration` | `b9156a8312fb3c8d927aa9e9d7d4dec31ffd9228` | `db323f0df4c5a7b1be8a7add696ad8404fae4975` | `/projects/loopino/clients/apple` |

Both histories remain independent on `loopino/phase1`. Author is Loopino Codex
<codex@loopino.ai>. The coordinator publishes commits using source-side authority;
this server must not acquire those credentials. `clients/apple`, `operations`,
`.toolchains`, `.cache`, `.venv`, `installation` and tenant runtime are ignored.

The source installation's developer-context documents were retrieved by the
coordinator. At the initial review no product CLI/backend existed on the destination, so the
canonical copied `docs/architecture/core_architecture.md`,
`workspace_root_architecture.md` and `app_contract_architecture.md` are the
initial review surface. Once the isolated CLI exists, use its developer-context
surface. No production installation's CLI is used.

| Old family | New contract |
| --- | --- |
| Maverick, Maverick v3, MAVERICK, LoopinOS | Loopino (display), LOOPINO (uppercase) |
| maverick, maverick-v3, maverick3 | loopino; never loopino-v3 |
| MAVERICK_* | LOOPINO_*; writers and readers change together |
| @maverick/*, Maverick SDK/types | @loopino/*, Loopino SDK/types |
| .maverick, .env.maverick | .loopino, .env.loopino |
| maverick.* schema/event, maverick-* cache/cookie/header/protocol | loopino.* / loopino-* with the existing suffix and version |
| native MaverickMac/MaverickDev, bridge globals and callbacks | LoopinoMac/LoopinoDev, Loopino bridge symbols |
| skill maverick-* IDs, filenames, generated instructions | loopino-* IDs and matching runtime references |
| /home/ubuntu/projects/maverick-v3, /opt/maverick* | /projects/loopino or explicit installation-root derivation |
| repository-parent signing/artifact/cache siblings | protected ignored installation-owned directories below the root |

Inventory includes every tracked first-party source, custom/backend-only apps,
lock metadata, installer/deployment templates, workflows, native packages, browser
companion, Senses/device transport, PWA and serialization. Dependencies, vendor
source, Git history and generated bundles are excluded from textual edits.
Third-party SDKs, trademarks, release URLs, signing team IDs and actual historical
GitHub evidence links retain their identities. Graphic content bytes, including
embedded lettering, remain conserved; filenames and references are renamed.
The graphic hash manifest records both source paths and destination paths.

The exact pre-change identifier/path/URL inventory and external CLI session ID
are in ignored `operations/phase1`. Source contracts and graphic hashes are
reviewable in source. Company-specific sources remain available for explicit
installation; clean first boot must enable only the installation's standard app
selection without Core/Shell app-id exceptions.

## Approved endpoint decision

Coordinator-approved public catalog: `https://loopino.giuntitrail.com/catalog`, serving the
existing `api/apps` catalog and immutable checksum-addressed bundles beneath
that prefix. This uses the authorized hostname and avoids new DNS dependencies.
Tranche 1 prepares generation and local schema/installation checks. The URL must
be served and verified during the separately authorized deployment tranche.

The old `https://maverick-app-store.versy.ai` must not remain an active product
default. No replacement repository is invented: GitHub links to
`PeterPsy/Maverick` and `giuntiocram/maverick-glasses-ios` are source provenance
or historical build evidence until the coordinator supplies published Loopino
repository destinations. Active workflow source retrieval uses
`GITHUB_REPOSITORY` and the exact dispatched commit. Third-party registered URLs
remain unchanged. Default product origin is `https://loopino.giuntitrail.com`.

## Reviewed implementation boundary

The coordinator approved `data/app-artifacts` as the single permitted artifact
store, including denial of symlink ancestors and traversal IDs. Node closure
trust admits only the protected declared distribution beneath `.toolchains`;
its real binary and ancestors must be root-owned and not group/world writable.
TLS/browser-origin/ACME/credential/log defaults remain installation-owned.
Hosted services explicitly select `.env.loopino`, installation-owned service
HOME and empty provider-auth homes. No operator login is copied or selected.

The standard selection is also the skill-template inclusion boundary and the
catalog export boundary. All distributed sources can be registered, while
unselected custom apps require explicit installation. Verification bindings and
random verification secrets are isolated operational material, not deployment
accounts. Browser install/migrate no longer auto-starts a Lab worker.

## Typed phase 2 migration inventory

`loopino_phase2_identity_map.json` records exact environment/worker messages,
protocol/schema/URI/local-state identities and their original source owners.
The full pre-change token/path/URL inventory remains in the ignored operations
record. Phase 2 must interpret each owning schema and cryptographic domain;
persisted state must never undergo a blanket text replacement. This tranche
neither migrates predecessor data nor accepts predecessor aliases.

Cookies, grant URIs, workspace/artifact markers, provider IDs, runtime adapters,
PWA/Keychain/local state and cryptographic domain prefixes change at their
writers and readers. The Core and native Device Use digest is pinned together
at `393689b7d1fc701ccf70d85da73e836a3989b27d4e55e9ebaa6829e3f378735d`.
The hook trust hash changes because the exact command identity changed; its
validation and fail-closed behavior remain in force. The final rebuilt executable
closure and admitted read operations were reviewed before refreshing all 46 exact
descriptor/executable surfaces at audit revision
`2026-10-14-loopino-phase1-reviewed-v16`. The artifact checkpoint preserves every
authority check; a subsequent executable change requires another review/refresh.

The phase 1 toolchain uses the isolated `.venv` editable `loopino` distribution;
its predecessor distribution/CLI/generated egg-info were removed through pip and
verified absent. Deployment TLS dependencies are the `installation` extra. PHP
8.3 CLI was extracted from the official host distribution package under
`.toolchains/php-cli`; `.toolchains/bin/php` runs it with `-n`, so preview tests do
not read unrelated host PHP configuration. This resolved the actual Website
Studio preview failures without changing runtime policy or assertions.

Runtime tokens now identify `loopino.runtime-api-token.v2`; provider aliases use
`loopino_` with the existing digest/truncation constraints. Design Studio native
message/request/project identities and PWA default/fallback idempotency keys use
the exact Loopino prefixes recorded in the typed phase 2 map. Secret envelopes
use `loopino.secret-value.v1-aesgcm`, reject every predecessor/unknown/plaintext
shape, and retain authenticated secret/key identity and keyring recovery. Phase 2
must decrypt original AAD and re-encrypt new AAD; metadata-only migration is
invalid. No existing-company source or state was changed.

The isolated official CLI is now installed and its developer-context surface was
used to verify the active working agreement. Reusable branch guidance preserves
the source branch at the deployed commit; `loopino/phase1` is this candidate and
`design` remains historical provenance. The predecessor editable distribution,
entrypoint and generated egg-info were removed with normal pip uninstall; only
Loopino is active in this installation environment.

Final source protection includes tracked source and real source/Git parents,
root-owned without group/world write. Mutable data/provider/runtime paths were
excluded from that handoff. Certbot uses the source-owned
`scripts/deploy/loopino-certbot` launcher and untouched 5.8.0 isolated distribution.
Its private namespace masks ambient CLI defaults; root-owned privileged HOME/XDG
and Python `-I` protect worker/after-tick startup before imports. No global
Certbot configuration, OS log policy or other site's routing was changed.
