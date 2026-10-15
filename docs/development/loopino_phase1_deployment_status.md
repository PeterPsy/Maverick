# Loopino phase 1 deployment checkpoint

Current server-setup acceptance is recorded in the
[activation checkpoint](loopino_phase1_activation_status.md).

> Historical snapshot: paths, branch names and live observations below belong to
> their recorded checkpoint or predecessor installation. Current destination and
> acceptance evidence are in [the root relocation report](loopino_root_relocation_status.md);
> they do not prove the new destination or its pending human setup gates.

2026-10-14. The new destination serves main HTTPS, login, standalone `/setup`
and the generic catalog. All 26 standard apps are registered and enabled.
This is a deployment review checkpoint, not phase 1 completion: new Cloudflare
and runtime-provider setup, wildcard/native/client acceptance and product visual
review still require the human/coordinator. No predecessor migration occurred.

## Source and artifact identity

Both repositories preserve `loopino/phase1`. The accepted source gate was platform
`ed1e34c758ab908e4523ca6f47ba17b2d20de68e`; Apple remains
`95909ece47b0a14dce255c905d26a1f604676715`, clean and unchanged here.

| Corrective platform checkpoint | Purpose |
| --- | --- |
| `610aa34a76513c7425df7bc77323cf9978037317` | Core owns host primitives; fresh artifact publisher and private runtime/socket parents |
| `d81d43138b9fb533b971fd546a0a948df006c5d2` | PyAV below 19 for the real faster-whisper decoder API |
| `6a431185b68b12f5511d507912e0bdc1cf532629` | Rooted Browser cache/libraries; direct service launch honors persisted owner stop |
| `d5d60774d181bb1a160b75c208c454a668670c7d` | Pinned new local OpenWA provider/toolchains and reproducible npm dependency closure |

The final documentation commit and exact live config/component hashes are recorded
in ignored `operations/phase1/deployment/deployment-manifest.json` after committing.
The coordinator publishes source with the existing source-side native authority;
no source credentials or predecessor provider credentials were copied here.

All 46 hosted authority surfaces match revision
`2026-10-14-loopino-phase1-deployment-v17`. Only Browser's two executable hashes
changed from the accepted gate. Descriptor bytes, admitted read operations and
authority checks remain unchanged. The delta receipt is
`deployment/authority-pin-delta.json` under `operations/phase1`.

No frontend or companion source changed during deployment. The accepted 25 mounted
manifests and 301 declared asset files were revalidated; builds were reused.
The full SDK export revalidated all 26 selected packages, metadata, checksums,
archive members and exact packaged source bytes. Current public index SHA-256:
`2863f2c18bf0a5cf01890b3adce30d5f5cd825277869a7ec305d4d6186b04006`.
All public HEAD lengths and four representative source downloads match their stored
digests. Earlier immutable package URLs remain intact. Original catalog receipts
are retained with supersession records pointing to this exact set.

## Live ownership and infrastructure

Everything owned by Loopino remains under `/projects/loopino`: source, independent
Apple repository, toolchains, certificates, keys, provider homes, tenant data,
cache, durable jobs, logs, catalog and operator evidence. User/group `loopino`
(UID 997/GID 988) owns only required mutable material. `.env.loopino` remains
root:loopino 0640 beneath protected real parents. Actual service-user read passes;
write, unlink and rename attempts fail. Source, `.venv`, `.toolchains`, privileged
HOME, issuer config and privileged log parents remain protected.

Core uses 127.0.0.1:8014; rescue uses 8015. Enabled product units are Core, rescue,
Browser Lab, the new local OpenWA provider, the installation timer/worker and the
backend watchdog timer/worker. Unit backing files and logs are under
`installation/systemd` and `installation/logs/systemd`; only matching registration
symlinks and OS unit metadata live outside the root. Nginx backing is
`installation/nginx/loopino.giuntitrail.com.conf`, registered through its own
sites-available/sites-enabled symlinks. Catalog/ACME routes remain present; no
new default server or neighbor routing changes were made.

The main certificate and ACME state are under `installation/tls/certbot`, with
webroot `installation/acme`. The isolated source-owned Certbot launcher masks
ambient CLI configurations and uses the protected privileged HOME/XDG context.
Main-host HTTP-01 renewal dry-run passed. Native external-wildcard activation
remains pending the new credential and an approved native plan; non-root
`managed_exact` issuance remains explicitly unsupported. No origin downgrade,
Cloudflare mutation or token-dependent plan/apply was used during this checkpoint.

The exact Bubblewrap AppArmor profile is rooted at
`installation/apparmor/loopino-bwrap` and registered with one exclusive OS symlink.
The global host user-namespace restriction remains enabled. Actual UID 997
namespace execution and the production Node runtime mount planner passed:
Node 24 executes, private data writes work, protected Node writes fail. The real
Design Studio confined sidecar returns native state with zero projects; its model
bridge correctly remains degraded without a new provider connection.

## Fresh standard app and provider state

`apps/bootstrap.json` selects exactly the 26 current catalog IDs. Initially all
26 bindings existed, but Browser and OpenWA failed genuine local-service health
checks. Settings and Vault were already enabled and filtered from the role-less
service CLI by their admin visibility contracts. Read-only diagnosis found no
contract, compatibility or source-resolution exception across the 26. After
provisioning the real prerequisites, authenticated admin inventory confirms all
26 enabled; role-less CLI correctly lists 24. The two company-specific sources
remain available source only and uninstalled. No visibility or health gate changed.

Browser uses Playwright 1.60.0 with protected in-root Chromium/cache/libraries and
a new private broker token. Both controller and direct worker require the same
real non-symlink enabled flag. Live owner stop, clean disabled service relaunch
and explicit enabled restoration passed without host reboot. The Lab is left
enabled/ready, with smoke sessions closed. Public MCP create/navigate/snapshot/
close passed using the installed `browser-ops` workflow. The new admin backend
request for a development inspector was denied by policy; no actor claim was
manufactured. Product desktop/mobile and human Chrome connector acceptance remain
unverified.

OpenWA is the pinned public upstream 0.24.0 revision
`8a45366a287750cf52c2658b0b783747cf51fad2`, built under `.toolchains` with the
checked-in npm lock. Its new loopback gateway uses protected Node, PM2 7.0.4 and
Puppeteer Chrome 146.0.7680.31, a new Core-owned secret/grant and private workspace
state. Provisioning used the fresh authenticated admin's official owner HTTP
surfaces, not an invented CLI actor. Authenticated session inventory is empty;
no pairing, account action or message send occurred.

Codex 0.162.1 is explicitly selected from the protected installation distribution
and executes as `loopino` with isolated Node. Provider homes contain no auth,
config or rules copied from root development login. Empty Codex scratch directories
can be created by its version probe; they are not a provider connection. The 25
seeded workspace skill copies match bundled source bytes. Canonical developer
context works through the installed CLI; real provider-generated session
instructions and agent/tool execution await the fresh provider connection.

Real local Speech uses espeak-ng/FFmpeg and a pinned public local small Whisper
model, all under `.toolchains`. Mounted local synthesis and CPU/int8 transcription
passed using the documented empty secret selector and `local_only` balanced
profile. Missing remote credentials still fail explicitly. Storage write/read/
owner-delete and missing-file/escape denial passed. A new opaque secret was
created, rotated and revoked through Core; owner audit/revoked metadata remain.
Temporary Storage and Browser fixtures were cleaned through their owners. Speech
retains its governed derived cache and metadata-only local smoke history.

## Verification and original failures

Complete receipts/commands are under `operations/phase1/deployment`.

| Settled check | Result / receipt |
| --- | --- |
| Core provisioning/import, DNS/Nginx primitives and persistence | 25 pass, `host-primitives-separated-env.log` |
| Browser Lab flag/environment and foreground descendant lifecycle | 6 pass, `browser-lab-lifecycle-final.log` |
| OpenWA native regressions | 46 pass, `openwa-settled-tests.log` |
| Hosted authority admission after final pin refresh | 5 pass, `authority-admission-tests-final.log` |
| Changed-source convention module | 15 pass, `conventions-deployment.log` |
| Tracked Python source unused imports / whitespace | clean; third-party downloaded source excluded by tracked-source selection |
| Main certificate renewal | real success, `main-http01-renewal-dry-run.log` |
| Live owner/local engines | `speech-backend-transcription-local-only.json`, `storage-secrets-owner-smoke.json`, `openwa-empty-unpaired.json` |
| Public catalog / exact 26 source packages | `public-catalog-current.json`, `catalog-verification-deployment.json` |
| Actual permissions, health/read consistency, neighbors | `service-permissions.json`, `live-health-neighbors-settled.json` |

The accepted broad source run and corrected Root retry are retained in the
historical source report; no unrelated full fast rerun was added for volume.
The original installer apply exited 3 after issuing the main certificate because
fresh service directories had incorrect/missing provisioning. Narrow ownership
and Core import fixes corrected startup; current real services are healthy.
`installer-apply.log` retains that failure. `host-primitives-focused-final.log`
is a failed ambient-environment test attempt; the separated-environment 25-test
retry is the succeeding evidence. Earlier OpenWA lock/PM2 launch errors remain
in their original logs. The first Speech inference's PyAV 19 failure is documented
with its traceback provenance; its overwritten local log is not claimed retained.
Invalid streaming WAV headers and omitted local-only/secret selectors were
corrected in smoke requests without weakening production validation.

Giuntitrail public/local HTTP and container status pass. Existing Giuntitrail and
Centrino Nginx registration targets/bytes match the pre-deployment baseline;
existing containers remain running. Only new Loopino services were restarted.
Status/stop/rollback instructions are in `deployment/rollback.md`; never delete
new tenant data or touch predecessor/neighbor services during rollback.

## Pending human and independent acceptance

Login is `https://loopino.giuntitrail.com/`, standalone setup is `/setup`. The
initial admin is `admin`; its password is only in the root-private operational
password file already handed off for SSH retrieval. No secret value appears here.
The human must enter the new Cloudflare token in protected setup. After coordinator
confirmation use official inspect/plan/apply/status/verify and durable native jobs
for wildcard issuance, random app-frame/sidecar HTTPS, renewal and maintenance;
credential-reference-only plan preparation is retained in operations.

A new provider connection is required for real agent/chat/tool execution and
provider-generated instruction acceptance. Desktop/mobile product visuals,
Browser human connector/development context, Senses device/hardware and PWA/native
flows need their applicable live contexts. Managed Mac review and signed iOS
still await renewed runtime authorization and human Xcode/account/capability
provisioning for the new bundle ID. Unsigned compilation is not signed acceptance.
The coordinator/independent reviewer must review the settled source/config/live
delta and exact manifest. Phase 2/3 and predecessor data remain untouched.
