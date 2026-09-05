# PWA cache — complete app scope and resource privacy decision

Date: 2026-09-05

## Product approval

The product owner explicitly confirmed that CRM and Mail are included and that
the complete planned app scope must be delivered. The proposed reduced release
(Calendar/Chat in RAM only and CRM/Mail excluded) is rejected.

This approves implementing bounded persistent read models for Calendar, Chat,
CRM and Mail, alongside Website Studio, Storage, App Store and Fitness Coach.
It does not by itself certify an implementation, open rollout flags, or satisfy
the physical-device release gate.

## Approved data scope

| App | Included read models | Fresh / expiry | Per-entry / resource budget |
|---|---|---|---|
| Calendar | Normalized bounded event windows, event details and non-secret calendar display metadata | 60 seconds / 6 hours | 1 MiB / 16 MiB |
| Chat | Recent projects, thread display metadata and bounded completed user/assistant messages | 30 seconds / 6 hours | 1 MiB / 32 MiB |
| CRM | Recent lists, pipelines, schemas and consulted customer records | 30 seconds / 6 hours | 2 MiB / 16 MiB |
| Mail | Non-secret mailbox/folder display metadata, recent headers/snippets and consulted sanitized message bodies | 30 seconds / 1 hour | 1 MiB / 16 MiB |
| Fitness Coach | Already-sanitized bootstrap and bounded thumbnail read models | 5 minutes / 24 hours | 512 KiB / 16 MiB |

These are resource ceilings, subordinate to the SDK's global/per-app budgets,
available quota, LRU eviction and private access lease. They are not a promise
of local availability. Pagination, event intervals and message windows must
remain bounded; a response that cannot safely fit must use the normal server
result rather than silently truncate the UI.

The approval covers the personal-data resources above and the explicit CRM/Mail
customer-data allowlist. Each owning adapter must project only reviewed fields;
it does not authorize arbitrary backend responses, custom/forked app identities,
or every resource in an app. Storage attachments use Storage's existing exact
file/version classification and approval mechanism, not an exemption based on
their originating app. Unclassified file bytes remain ineligible until that
mechanism approves them.

## Invariant exclusions

- OAuth tokens, passwords, app credentials and secret values;
- signed or object URLs and local server paths;
- provider/session/tool payloads and agentic control-plane authority;
- authorization, admission, confirmation and revocation decisions;
- active runtime operations, unbounded technical event logs and live streams;
- persistent mutation queues, delayed sends and local acknowledgements of work
  that the server has not confirmed.

App inclusion must not weaken exact user/workspace/app scoping, host-owned
storage, lease checks, expiry, authorization revocation or durable cleanup.
Cache-derived display data never grants permission to perform an action.

## Completion and release

1. Implement each approved adapter, strict sanitizer, stable revision,
   conditional revalidation, invalidation and ordinary loading/cancellation.
2. Retire superseded app-local caches without trusting unscoped legacy payloads.
3. Verify warm paint, unchanged responses, changed-data refresh, missed/expired
   entries, malformed payloads, terminal authorization, cancellation and cleanup.
4. Build the exact candidate and validate its physical-device matrix (PWA-098).
5. Execute the runbook's controlled cohorts and rollback drill before general
   rollout. Existing default-off flags are unchanged by this decision.

Privacy consent is recorded; technical enforcement and device/rollout evidence
are separate deliverables. None of the listed apps may be silently dropped or
relabelled RAM-only merely to declare the plan complete.
