# Loopino canonical-root relocation checkpoint

The live installation and both independent repositories now reside at the real
`/root/projects/loopino`. Main HTTPS, login, standalone setup and the generic
catalog are available at `https://loopino.giuntitrail.com`. All 26 apps selected
by `apps/bootstrap.json` are installed and enabled; GitHub Actions and Marta Ops
remain available source only. This is a phase 1 relocation checkpoint, not phase
1 completion. No predecessor migration or Mac configuration was performed.

## Source and evidence

The accepted pre-move platform was `9d906b2b38ac46270b621ba6f47fbde476151431`,
with Apple `95909ece47b0a14dce255c905d26a1f604676715`. Both histories retain
`loopino/phase1`. The membership correction is checkpoint `c1f0be18`.
Apple's subsequent change documents the server path and Mac-last order only.
Exact final commits, backing configuration hashes, toolchain/model identities,
artifact sets and live receipts are recorded in the ignored
`operations/phase1/relocation/verification/deployment-manifest.json`.
The coordinator publishes bundles using source-side Git authority.

The accepted executable audit remains
`2026-10-14-loopino-phase1-deployment-v17`: all 46 exact descriptor and execution
pins match. No admitted operations or authority checks were broadened. Production
frontend and companion source did not change, so the existing 25 frontend
manifests and all 301 assets were verified and reused. Path-bearing app docs,
examples and tests were repackaged through the real SDK catalog exporter. Every
current package's metadata, digest and archive source bytes were checked; public
HEAD lengths and four representative downloads matched. Previous immutable
package URLs retain their original bytes. The current index digest and package
list are in the manifest; earlier catalog receipts are explicitly superseded.

## Preservation and trust

Only Loopino services, timers and writers were stopped for the same-filesystem
rename. The coherent private rollback snapshot under
`operations/phase1/relocation/before-move` was independently verified as 19,074
regular files / 724,301,010 bytes with no missing or mismatching files. Initial
failed attempts involving terminal Speech sockets are retained as failed receipts.
No tenant text, attachments, chat, database bytes or encrypted envelopes were
blanket-replaced. AppStore adapters, running as UID997, changed only 28 registered
source paths and 26 workspace binding data roots. Native environment fields and
Certbot ConfigObj renewal path fields were rebased separately, preserving the
existing main key/certificate/account. Python runtime distribution versions were
preserved while editable metadata and console entrypoints were reinstalled.

Repeated bootstrap had previously recreated membership timestamps. The correction
preserves existing identity and creation time, keeps active unchanged memberships
unchanged, and retains role changes/reactivation. Role inputs normalize to `admin`
or `member` before either branch. Only the affected original membership timestamps
were restored with identity/role/status assertions. Final checks match every
original user, credential, membership, encrypted value and grant field, plus the
bootstrap keyring and certificate bytes. No re-encryption occurred.

`/root` has no other/world access. Named ACL traversal permits UID997 and host
Nginx's dedicated `loopino-ingress` GID987 only. Blocker ancestors deny these roles
access to other root-home entries and sibling projects, with default denies for
future children. No recursive denies were applied. The Giuntitrail container's
UID33 lacks GID987 and retains its original bind-mount access; all six fresh host
Nginx workers have the ingress group. The extracted official ACL package and
exact restore metadata stay under the installation. Source, immutable artifacts,
toolchains, privileged HOME and log parents remain protected. The shared service
and privileged worker environment remains root:loopino0640, readable but not
writable/unlinkable/renameable by Core. Core/provider homes remain separate and
writable only where required. No root operator auth/config/rules were adopted.

All Loopino systemd/Nginx/AppArmor backing, logs, TLS/ACME material, caches,
dependencies and operational records use the new root. OS entries are exclusive
registration links; existing neighbor routing and default-server bytes are
unchanged. The service account remains UID997/GID988 with its new in-root HOME.
The source-owned isolated Certbot launcher, protected privileged HOME and Python
`-I` boundaries remain intact; three real privileged startup checks passed at the
new root. Main HTTP-01 renewal dry-run succeeded there. The actual configured
browser-origin mode is `external_wildcard`; no unsupported non-root exact issuer
or alternate privilege bridge was introduced.

## Verification

Complete commands/results and retained failures are under
`operations/phase1/relocation`. Relevant passing checks include:

- membership/workspace bootstrap: 15 tests; trust/envelope/artifact/membership:
  45 tests; final path/registration/protected material: 19 tests;
- installer/egress fixtures: 46 tests; provider paths: 18 tests;
- CRM service: 52 tests; Website Studio entrypoints: 114 tests;
- External Apps deployment: 2 tests, one explicit opt-in Nginx proof not rerun;
- OpenWA: 46 tests; Browser lifecycle: 6 tests;
- repository conventions and authority audit: 16 tests; unused imports: clean;
- Chat path fixtures: 71 tests across three files; no production frontend rebuild;
- actual UID997 CLI from `/`, protected Node/Bubblewrap overlay and hosted
  Design Studio state; all 26 app contracts, compatibility and source paths;
- fresh admin login, anonymous administration/backend denial, Storage path-escape
  denial, Storage create/read/delete and secret create/rotate/revoke cleanup;
- real local Speech synthesis/transcription and missing remote-secret rejection;
- Browser owner stop followed by disabled direct service launch without children,
  then explicit restoration to enabled/ready; OpenWA ready and still unpaired;
- service identity/path permissions, exact seeded skills, empty provider auth homes,
  unchanged Giuntitrail registrations/HTTPS/containers and Centrino private ports.

Wrong invocation, stale path/role expectations and unsuitable service-writable temp
parent attempts remain recorded separately. Their passing retries use isolated
fixture installations and protected `.t` temporary directories; no production gate
or assertion was removed to pass. The earlier retained full fast suite is historical
154-group evidence (153 groups passed; affected Root retry passed 1,672/8 skips),
not a new all-green full-suite invocation. It was not repeated for this narrow move.

## Handoff and remaining gates

The human uses protected `/setup` with username `admin`; the root-private password
file is `operations/phase1/access/initial-admin-password` (0600), retrieved through
SSH without sharing its value. Cloudflare setup, native wildcard plan/apply and
renewal, fresh provider connection and real agent/chat/tool acceptance remain
pending. Only native authorized installation surfaces may consume the new
credential references. No DNS job was invented or applied without confirmed new
credential state. Public login screenshots were inspected at desktop and mobile sizes: the form
fits both viewports and explicitly reports Google sign-in unconfigured. Conserved
logotype lettering remains the agreed graphical-byte exception. Default Browser
snapshots work; newly observed optional `max_chars`/`max_items` fields are advertised
by discovery but rejected by the unchanged app action. Original 400 receipts are
retained for independent app-contract review; no gate was relaxed. Authenticated
Browser/Companion, workspace desktop/mobile visual, PWA and native/hardware
acceptance remain explicitly scoped in the manifest.

Mac account, signing, build/device configuration is LAST after remaining server
work and human server setup; unsigned compilation is not signed acceptance.
Independent final delta/live review and coordinator publication remain required.

The temporary old-root alias exists only for this foreground supervisor. Product
roles are denied access and every product path uses the new real root. After this
CLI exits, the coordinator must verify `/projects/loopino` is a symlink whose exact
target is `/root/projects/loopino`, unlink that alias only, and repeat independent
checks from the real root. It is not retained product compatibility. Exact stop,
status and data-preserving rollback steps are in the private relocation record.
