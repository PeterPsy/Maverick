# Usage SQLite cutover with the backend stopped

Usage migration must finish before any backend or runtime writer starts with the
new adapter. A running agent must not promote its own Usage database and then
continue producing observations through the old adapter.

For a systemd-managed host, an operator can install the explicit one-shot
`core.usage.startup_maintenance` entry point as a temporary `ExecStartPre`.
This invokes the existing Usage prepare, validate, cutover and backup operations
under their shared exclusive fence. It does not change normal bootstrap or run
from a read. The service must use `KillMode=control-group`; the command refuses
a live main process, another startup control process, or an undrained unit.
Independent CLI or external Usage writers must also be stopped for maintenance.

Before activation, complete verification, retain the deployed source revision,
and arrange a maintenance restart with all agent-owned tests/builds stopped.
Use the verified SQLite runtime (at least 3.51.3). Preserve the existing service
environment, user/group and library-path configuration. Configure the next
backend with `MAVERICK_USAGE_STORE=sqlite`; ensure later environment files do not
override that setting.

Example temporary service drop-in, with paths changed to the actual installation:

```ini
[Service]
Environment=MAVERICK_USAGE_STORE=sqlite
TimeoutStartSec=300
ExecStartPre=/srv/maverick/.venv/bin/python -m core.usage.startup_maintenance --repository-root /srv/maverick --receipt /srv/maverick/data/control-plane/usage/maintenance/cutover-2026-09-20.json
```

Reload the service configuration and use the managed backend restart. The next
prestart runs after the previous control group has stopped and before HTTP,
runtime recovery, hooks or providers can start. Its receipt records the immutable
source candidate, canonical digests, validation, promotion and verified backup.
A failure prevents backend startup; inspect the receipt and service journal
before retrying. A lost acknowledgement after promotion resumes the same
migration. A changed source or unrelated active migration fails closed.

Once `/health` succeeds, use `core.persistence.usage-status` to verify
`adapter=sqlite`, `configured_adapter=sqlite`, `restart_required=false` and the
expected counts. Verify subsequent real Usage observations and an owner backup.
Then remove only the temporary `ExecStartPre` and timeout override, retain the
SQLite environment selection and reload the unit. Retain the receipt and Usage
backups. A completed receipt is a no-op, even following an intentional rollback;
each new cutover requires a new receipt path.

Rollback remains an explicit, drained Usage owner operation. It exports the
current database, including every post-cutover observation, before selecting the
document adapter. Never reactivate the frozen original JSON after new writes.
Restore the document environment selection for the next backend and remove the
temporary startup cutover hook before reopening traffic. The migration tests
exercise reverse export after new observations, source-change rejection and
retry after promotion; keep these checks green when changing this workflow.
