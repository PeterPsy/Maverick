# CRM operational integrations

Date: 2026-09-19

## Scope and ownership

The generic CRM integrates Mail, Calendar, Storage, Checklist and Speech. No Versy
production migration is required. Campaign behavior is unchanged and excluded from
these new flows. CRM owns relationships, meeting context and approval records;
providers own messages, events, files, external tasks and transcription execution.

## Governed execution

Use `dependency_backend_requests`, never subprocess CLI fallbacks, provider private
files or direct credentials. The core resolves selected aliases and calls CRM's
backend callback. Only the core-stamped callback surface may complete operations.
User bodies cannot forge this surface. Search/resolve requests persist bounded
receipts, so their CRM actions are declared mutating; reading receipts is read-only.

External writes are prepared as immutable integration operations with ordinary CRM
workflow proposals. Approval and execution are separate. Execution checks the
current provider selection, claims a unique attempt transactionally and records
its result. Repeated execution must not repeat a running/completed operation.
Provider timeout or loss of callback means uncertain delivery, not permission to
retry. Only read operations and writes with a provider-supported idempotency key
may be retried; non-idempotent writes require explicit identity reconciliation.

Mail drafting is integrated; sending stays in Mail, where the human reviews the
actual draft and Mail enforces its own preview/approval. CRM never exposes an
arbitrary provider action runner or a campaign send path.

Mail, Calendar and Speech backend entrypoints explicitly handle the core's
`secret_selector` preflight without executing the requested business action.
Calendar creation here is native Maverick scheduling, not Google invitations.
Storage writes are create-only Markdown documents under `storage/generated/crm/`.

## Sync and business workflows

Only explicitly linked references are refreshed, in bounded batches. Provider
errors retain the last good snapshot and record freshness/error state. Missing
remote records are marked missing, never delete CRM records. Provider UI events
and a bounded background hook refresh due references; no browser polling and no
new detached process. Existing links are retained, but automatic sync requires
explicit opt-in or a new verified link.

The hook considers up to 200 supported opted-in references per pass, oldest first,
and resolves up to five links due every five minutes. Manual refresh resolves up
to ten links. Legacy/unsupported links are filtered before the scan limit so they
cannot starve opted-in work. A trusted linked-provider UI event coalesces for five
seconds before refreshing the visible record. No account-wide background sync or
automatic business write is introduced.

Meeting briefs are deterministic compositions of linked CRM context and provider
snapshots, not invented AI summaries. Recording outcomes creates an activity and
reviewable follow-up proposals. Speech reads an explicitly linked Storage audio
file and produces a reviewable note proposal; its text never authorizes actions.
Checklist tasks remain Checklist-owned; CRM displays their status and may propose
status updates without maintaining a second editable task copy.

Integration receipts round-trip as history, never imported execution authority.
Imported workflows cannot overwrite a local operation's immutable approval record.
Delete/merge is refused for records with receipts; archive is refused while an
operation is running. Resolve or reconcile the operation first. These restrictions
avoid silently retargeting previously approved external effects.

## Release validation

Test selection changes, callback forgery/replay, concurrent execution, uncertain
outcomes, idempotent retry, failed refresh preservation, native export/import and
real isolated provider contracts. Build through Maverick and compare existing CRM
business data before/after the additive backed-up migration. No production email,
calendar event, file, task or transcription is created during verification.

Release 0.6.0 / schema 8: 109 Python tests and 15 Chromium browser tests pass,
including isolated real provider entrypoints, separate approval/execution and
desktop/mobile CRM integration flows. TypeScript, unused-import checking, SDK
validation and the official frontend build pass. The live CRM reports healthy
schema 8; every pre-existing business table matches the schema-7 backup row for
row, including all 15 external references, intake receipts and notification outbox.

Workspace `default` retains its existing Mail/Calendar/Storage selections. The
operator-requested configuration additionally selects Speech and Checklist for the
previously unconfigured optional aliases. Speech's official engine health reports
its selected transcription engine available; no real audio was submitted or
credential copied. These workspace selections are runtime configuration, not
hardcoded provider identities or seeded business data.
