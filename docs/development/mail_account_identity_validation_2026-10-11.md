# Mail account identity and workspace mailbox recovery

Date: 2026-10-11. Branch: `design`.

## Result

Mail, Calendar, Storage and the central Connected accounts dialog identify
accounts by email first and display name second. Inline Mail sender and Calendar
destination labels include both in that order. IDs continue to identify actions,
filters and provider requests, including accounts with identical display names.

Mail now imports pre-existing workspace IMAP/SMTP connections into the authorized
personal app view when Google accounts are enabled. The app-owned, transactional
import preserves connection IDs, folders, labels, message/attachment cache,
drafts, sync state and associated links/audit records. Existing destination
records win on retries, and the source database remains untouched. The import
excludes shared Google records, credential values, OAuth state and pending send
approvals. Vault metadata is reconstructed for the original workspace/resource;
Core password grants remain authoritative. The SDK validates the trusted source
path, refuses symlinks and marks a successful import once under its migration
lock. Core overwrites any supplied workspace source with the authorized binding.

Actual recovery in `default` restored the original Private Email connection
`team@loopino.ai` beside all five connected Google accounts. This was the saved
address; no configured `team@loopino.com` connection was recovered. The existing
password grant authenticated successfully with both IMAP and SMTP. Mail's
activation action restored active credential metadata, and a bounded IMAP sync
read ten messages. A Gmail sync for the default account also returned HTTP 200.
No message was sent.

Visual inspection also exposed a Storage regression: managed Google accounts
had no app-owned Vault credential reference and were incorrectly rendered as
`Reconnect required`. The sidebar now accepts a connected Core-managed
projection with a matching account ID, while still respecting disconnected/error
states and the credential checks for manual connections. All five Drive search
checks returned HTTP 200. The actual mobile frontend opened the default
account's My Drive and listed its folders/files without another OAuth prompt.

## Automated validation

All final focused suites passed, totaling 339 tests:

| Suite | Tests |
| --- | ---: |
| Core identity, account brokers, policies and migrations | 90 |
| Mail backend and entrypoints | 152 |
| Mail account labels, sidebar, draft reader and filters | 31 |
| Calendar account groups, filters and destination labels | 14 |
| Shell connected-account selection and presentation | 5 |
| Storage connection status, API and Drive navigation | 47 |

Python verification used the repository virtual environment and the production
SQLite 3.51.3 library via `LD_LIBRARY_PATH`. The relevant unused-import check and
`git diff --check` passed. Mail, Calendar, Storage and base-shell were rebuilt
through their official frontend build surface, including committed dist assets.
Storage was rebuilt again after correcting the managed-account status check.

## Runtime and UI validation

The backend was restarted after the Core/SDK changes and reported healthy.
Authenticated Browser dev-inspector sessions checked desktop 1440×1000 and
mobile 390×844. Mail showed six connected mailboxes; Calendar and Storage showed
five Google accounts, with email before the display name. Storage's sync controls
were enabled after the correction. The Google settings entry remains in the
sidebar header, and its dialog uses the same email-first order. Workspace Google
selection and the default account were preserved.

The mobile session recorded no console errors. The long-running desktop session
recorded HTTP 401 errors from an obsolete Calendar frame during navigation away
from Calendar; a fresh authenticated desktop Calendar session was checked
separately and recorded no console errors. Provider checks and the active Storage navigation succeeded. All
owned Browser sessions are closed at the end of verification.

The shared hosted frontend was checked at desktop/mobile sizes. No native
Mac/iOS binary was rebuilt, and no message sending, event creation or Drive
mutation was used as a test. Provider checks were bounded reads/syncs rather than
an exhaustive synchronization of every mailbox, calendar or Drive item.
