# Loopino phase 1 source status

Source review is still in progress; this is not installation or release acceptance.
Platform published checkpoint: `c8e2cfcd`. Apple corrective checkpoint: `ff4bd3a`
(on top of published `598ff29`). The coordinator publishes with source-side Git
credentials; this destination contains no such credentials.

Reviewed corrections now implemented: designated artifact-store ancestor and
ownership checks; installation-owned Nginx/systemd backing files with exclusive
OS symlink registrations and rollback; narrow private service ownership handoff;
empty installation-owned provider homes; exact frozen device contract correction;
unsigned iOS compile preparation with entitlements retained. No live registration,
service restart, TLS issuance or production-data migration has been performed.

Relevant checks passed in the isolated Node 24.11.0, SQLite 3.51.3 (FTS5/RTree)
and Bubblewrap 0.11.2 environment: 409 API tests; 76 app-hosting tests (before the
additional writable-ancestor case); 41 installation tests; 49 focused retry,
provider and installer tests. The full approved catalog export succeeded and all
26 package checksums, SDK manifests, version/presentation/distribution metadata
and source-only archive members were independently checked. Final regenerated
catalog and hosted authority pins must follow the final executable/build closure.

`fast-final-1` is a complete diagnostic run with 68 failure/error records, saved
under ignored `operations/phase1`. API model/reconnection and Research fixture
failures, deleted-cwd leakage, PWA retry policy drift, and handoff metadata checks
have corrections and focused passing verification. Remaining app/repository
contract and test failures are being diagnosed; a final fast run remains required.
No coverage or fail-closed authority checks have been removed to obtain acceptance.

All mounted frontends and Browser companion have been rebuilt sequentially through
the isolated official CLI. Affected apps require a final rebuild after the latest
contract/backend corrections, followed by manifest/graphic verification and exact
hosted read-authority audit refresh. Unused-import validation and final diff review
also remain final checkpoint gates.

Mac run `38626592532` compiled Swift and passed 308/309 tests; the sole stale frozen
fixture is corrected in `ff4bd3a`. The coordinator must rerun the managed Mac
build. Signed iOS run `38626666895` failed Xcode 65 because the new identifier
`com.giuntiocram.loopino.dev` lacks account/capability-enabled signing on the runner.
Human signing setup is pending; unsigned compile evidence is separate and cannot
substitute for signed/device acceptance. No installed client has been replaced.

Before deployment: independent source review, coordinator deployment tranche,
clean non-root service ownership/Bubblewrap/AppArmor verification, main HTTPS/login
and standalone setup, then human-entered new Cloudflare token and coordinator
notification before wildcard issuance/renewal checks. Giuntitrail, Centrino and the
other company's installation remain untouched. Provider auth is never inherited
from operator `/root/.codex`.

CLI session: `01a13bd0-26af-7660-828f-fb51aa30e24b`. Exact commands, full bounded
verification logs, commits and pending decisions live in `operations/phase1` and
are excluded from source commits.
