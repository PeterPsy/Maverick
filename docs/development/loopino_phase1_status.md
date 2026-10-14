# Loopino phase 1 source gate snapshot (historical)

> Historical snapshot: paths, branch names and live observations below belong to
> their recorded checkpoint or predecessor installation. Current destination and
> acceptance evidence are in [the root relocation report](loopino_root_relocation_status.md);
> they do not prove the new destination or its pending human setup gates.

This retained snapshot describes the accepted source gate before live deployment.
For current destination status, see [the deployment report](loopino_phase1_deployment_status.md).

At this source checkpoint on 2026-10-14, no live deployment,
OS service registration, Nginx reload, certificate issuance or production-data
migration has occurred. This report establishes source/build verification only.
Giuntitrail, Centrino and the predecessor company's installation remain untouched.

## Reviewable checkpoints

Both independent repositories preserve `loopino/phase1`. Platform source/artifact
checkpoint: `3b085d7e085a0002b10aee77b6a633d506b61144`. This report and the final
branch-guidance documentation follow that checkpoint; the exact report commit is
recorded in ignored `operations/phase1/status.md` after committing.

| Platform checkpoint | Result |
| --- | --- |
| `ec566dfd8d36adf6144cd33b6860b9fa1029cf64` | Artifact ancestor validation, exclusive OS registration symlinks and service ownership |
| `5d071adbfa07078980c5a3e42e831c1ec9bac242` | Coordinated fail-closed token, secret, alias, delegation and idempotency identities |
| `695d56e563e383a1332d830add3be4762c281982` | Protected shared env, installation-owned TLS, logs and backups |
| `e90c5458668c8c150739e6fd463caac3314e8559` | Persistence cutover authority checked before any target open or collection copy |
| `1a6ab87040ec1efdaeda1651b6d7b3b0a3eb8ae5` | Privileged Python/Certbot context isolation and explicit managed-exact role denial |
| `0145fb1c399c56ac937f4c3f63e06914425d248c` | Narrow protected Bubblewrap/Node executable trust |
| `5d9a59673dbd8552ee283b581d0f3de67d74dfb2` | Domain module/fixture ownership, unchanged convention ceilings and deterministic snapshot fixture |
| `2db2427a160b5b615b901341c1c92344dfb6ba1c` | Portable TLS fake-runner fixtures and explicit real operator-smoke opt-in |
| `d73bc3ad202d0a40920603863ffbd5bd51785aed` | Complete SDK app contracts/implementations and meaningful current integration fixtures |
| `3b085d7e085a0002b10aee77b6a633d506b61144` | All rebuilt mounted frontends, companion, conserved graphics and exact authority pins |

Apple checkpoint, already published by the coordinator:
`95909ece47b0a14dce255c905d26a1f604676715`. It preserves the legitimate lab merge
`2819a6e21442535a0166dfa1365b4e2f5f795e4f`, removes tracked bytecode, fixes the frozen
contract fixture and enables unsigned compilation with a narrow branch/path push
trigger. No native history was rewritten or installed client replaced. Publication
uses source-side authority; no source credentials were copied here.

## Settled source behavior

The [provenance/rename and endpoint map](loopino_phase1_provenance.md),
[typed phase 2 map](loopino_phase2_identity_map.json) and
[graphic hash inventory](loopino_graphics_sha256.json) record the identities and
exceptions. New runtime tokens reject predecessor identities. Secret envelopes
use `loopino.secret-value.v1-aesgcm` and reject predecessor, unknown and plaintext
shapes. Their AAD includes format, secret ID and key ID: phase 2 requires original
AAD decryption and new AAD re-encryption with verified keys, preserving IDs/grants
and testing recovery. Metadata-only migration is invalid; none was performed.

All new installation backing material stays under `/projects/loopino`. The only
admitted in-root artifact store is `data/app-artifacts`, with real protected
ancestors/app parents and existing namespace ownership/generation checks. OS
integration uses exclusive symlinks to protected `installation/nginx` and
`installation/systemd` backing files. Catalog and ACME routing survive rendering.
Application, worker, vhost logs and narrow recovery backups are installation-owned.

The shared service env is root-owned, group-readable `0640` beneath protected real
parents. Core cannot write/replace it. Mutable tenant/runtime/provider homes and
necessary key read access are separate. Service-user persistence apply returns
`host_operator_required` before opening a target or copying collections; an
authorized host operator performs cutover through the native CLI. Source,
immutable artifacts and toolchains stay protected.

Privileged worker/after-tick startup overrides the writable Core HOME before
Python imports, uses protected HOME/XDG paths and `-I`, and restores the protected
context after loading service configuration. Every offered Certbot consumer uses
`scripts/deploy/loopino-certbot` with the protected isolated 5.8.0 distribution,
rooted config/work/log arguments and private mount namespace masking ambient CLI
defaults. No installed third-party source or host Certbot configuration was edited.
The real smoke checks use synthetic defaults and perform plugin discovery, not CA
issuance. Non-root `managed_exact` is explicitly unsupported and fails closed;
the target uses `external_wildcard` through the existing trusted root worker.

Clean bootstrap/catalog select 26 standard apps. Marta Ops and other unselected
custom apps remain source-rebranded and require explicit inclusion. The approved
catalog is `https://loopino.giuntitrail.com/catalog`, using the existing schema and
immutable SDK bundles. Registered third-party/historical URLs were not fabricated.
Active guidance preserves the branch at the deployed commit; historical `design`
evidence is not an instruction to switch branches.

## Verification evidence

Verification used isolated Node 24.11.0, Python 3.12.3, SQLite 3.51.3 with actual
FTS5/RTree bindings, Bubblewrap 0.11.2 and bounded resources. The editable product
is only `loopino 0.1.0`; predecessor CLI/distribution/egg-info are absent. Provider
homes have zero files and never use the operator login. Tests use their own stores,
separate from official CLI build fixtures; see [source verification](source_verification.md).

`scripts/test_suite.py --level fast --jobs 1` completed all 154 command groups,
4,415 tests. Its preserved raw exit is **1**: the root-unit group had five protected
source-owner validation errors. The other 153 groups passed. Metadata-only source
protection corrected those errors. The first root retry exposed the same-tick
snapshot fixture; advancing its mtime preserves the rejection assertion. The final
affected root retry passed **1,672 tests, eight intentional skips**, exit **0**.
All broad-run groups therefore have passing evidence after the scoped correction;
the original full command is not relabeled as a zero-exit run.

| Check | Result |
| --- | --- |
| TLS fake-runner/role fixtures plus ordinary startup discovery | 25 tests pass, three explicit operator checks skipped |
| `LOOPINO_OPERATOR_SMOKE=1` real privileged startup/Certbot tests | Three pass; synthetic host/Core HOME settings excluded, DNS plugin found, vendor bytes unchanged |
| Convention checks / unused imports / diff whitespace | 21 pass / clean / clean; no gate ceilings or exceptions weakened |
| Provider / API / app-hosting coverage | 459 / 409 / 77 pass, with the latter two also in the broad run |
| Calendar integration / Device Use / isolated hosting-contract checks | 140 / 132 / 36 pass |
| Persistence pre-copy authority / hosted-effect contract checks | Eight / four pass |
| PWA cache / Shell frontend / Browser companion | 209 / 359 / 66 pass |
| Apple Linux checks | 49 tests, one Darwin-only skip; not Xcode acceptance |
| Official isolated frontend builds | 25 sequential mounted builds, including explicit custom-app preparation; Browser companion rebuilt |
| Frontend/graphics/artifact verification | 25 manifests, 301 declared assets, all 45 original graphic hashes conserved |
| Real SDK catalog export | 26 packages; every checksum, metadata, safe member and packaged source byte verified |
| Exact hosted authority audit | 46 surfaces at `2026-10-14-loopino-phase1-reviewed-v16`; checks retained |

The local catalog index SHA-256 is
`7828f07043cd47e30bf85f8da8ecdcb6b313766f4f7b4acfc1bf50a2b413371b`.
Its ignored installation output is prepared, not publicly served. All complete
logs, exact commands, original failures, retry results, package receipts and final
commit IDs remain under `operations/phase1`; generated bytecode, caches, secrets,
runtime stores and the nested Apple Git directory are excluded from platform commits.

## Work remaining at that source gate (historical)

Independent acceptance and coordinator `deployment-tranche.md` precede live work.
Fresh provisioning must generate new secrets/keys with intentional ownership,
isolate or discard verification stores, and verify actual Core-user env write
denial plus non-root Bubblewrap/AppArmor execution without host security relaxation.
Prepare main HTTPS/login/standalone `/setup` first. The human then enters the new
Cloudflare token and provider credentials through protected UI; wait for coordinator
notification before token-dependent wildcard issuance/renewal verification.

Fresh desktop/mobile app UI, login/setup, provider execution, public catalog/TLS
and wildcard renewal are unverified live surfaces. Mac run `38626592532` compiled
Swift and passed 308/309 tests before the frozen fixture correction; corrected Mac
acceptance remains pending. Signed iOS run `38626666895` failed Xcode 65 because
human Xcode/account/capability provisioning is missing for
`com.giuntiocram.loopino.dev`. Entitlements and the new ID remain intact; unsigned
compilation is separate from signed/device acceptance. Managed status awaits
renewed app authorization; no expired-token or credential bypass is used.

Phase 2/3 and predecessor production remain out of scope. CLI session:
`01a13bd0-26af-7660-828f-fb51aa30e24b`.
