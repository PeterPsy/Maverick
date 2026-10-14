# Loopino phase 1 source provenance and rename decisions

This is a clean installation, not a migration. Installation-owned source,
operational records, toolchains, dependencies, caches and runtime material are
rooted at `/projects/loopino`. Tenant data and provider credentials are created
fresh. The operator's `/root/.codex` login is external development authority only.
No live Nginx, systemd, Certbot or existing-service changes belong to tranche 1.

| Source | Baseline commit | Original tree | Destination |
| --- | --- | --- | --- |
| Platform, original `design` | `e76799d05941361e3d896cb2ddcdfbd0517fee3d` | `bf1db4e8c1e26ce0a399f6cadc893d4131e74e91` | `/projects/loopino` |
| Apple, original `maverick-integration` | `b9156a8312fb3c8d927aa9e9d7d4dec31ffd9228` | `db323f0df4c5a7b1be8a7add696ad8404fae4975` | `/projects/loopino/clients/apple` |

Both histories remain independent on `loopino/phase1`. Author is Loopino Codex
<codex@loopino.ai>. The coordinator publishes commits using source-side authority;
this server must not acquire those credentials. `clients/apple`, `operations`,
`.toolchains`, `.cache`, `.venv`, `installation` and tenant runtime are ignored.

The source installation's developer-context documents were retrieved by the
coordinator. No product CLI/backend exists on the clean destination, so the
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
validation and fail-closed behavior remain in force. The hosted builtin effect
audit stays fail-closed until the rebuilt executable closure is reviewed and
its exact pins are refreshed. That refresh is a separate artifact checkpoint.
