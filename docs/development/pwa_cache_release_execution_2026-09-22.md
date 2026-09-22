# PWA cache release execution, 2026-09-21/22

## Outcome

The structured PWA data cache is live on `https://maverick.loopino.ai` for the
eight reviewed app adapters. Service Worker v2 remains enabled. Storage file
and preview bytes remain server-first because their resource classification is
still `unclassified`; the physical-coverage waiver does not broaden that data
policy.

Final production state, verified at `2026-09-22T08:08:00Z`:

| Surface | Final state |
| --- | --- |
| Service health | `ok` |
| Service Worker | enabled, generation `v2` |
| Structured data cache | enabled |
| Enabled adapters | App Store, Calendar, Chat, CRM, Fitness Coach, Mail, Storage, Website Studio |
| Unexpected enabled adapters | none |
| Storage file cache | disabled |
| Cohort | 100% of the single production workspace and user cohort |

The 100% cohort is deliberate: this deployment has one meaningful live
workspace/user, so a lower deterministic percentage could select nobody. The
per-app gates still limit persistence to the eight reviewed resources.

## Candidate and release decision

- exact candidate release id:
  `97ba359a4e335b1ae432d0bdd582732688b599b0`
- Base Shell build id:
  `24da44656c1ae3e6d0bb791310a08c65f90d56c55ea839d0a6c01ee9dbcbdf4f`
- governed waiver implementation and record commit: `d65aba3d`
- waiver record:
  `docs/product/pwa_cache_physical_release_waiver_2026-09-21.json`
- waiver validity: accepted `2026-09-21T22:30:31Z`, expires
  `2026-09-28T22:30:31Z`

The waiver is exact-candidate-bound and records 17 pass, 0 fail and 52 pending
out of 69 physical outcomes. It does not convert pending rows into passes. It
permits this release owner decision for the remaining coverage only, while
malformed, stale, unredacted, wrong-candidate, privacy and resource-policy
failures continue to fail closed.

Physical evidence obtained before the waiver:

- runner diagnostic `35653396231`: success;
- iPhone Safari `35653611356`: success;
- macOS Safari `35653879706`: success;
- Chrome browser `35653947327`: success;
- Chrome installed app `35653993821`: success.

## Preflight verification

The exact integrated tree passed the release-specific gates before rollout:

- PWA cache package typecheck and 202 tests;
- Base Shell 231 tests;
- service worker and browser contracts, 17 tests;
- Settings cache controls, 5 tests;
- Website Studio logic, 39 tests, and visual suite, 4 tests;
- waiver/device-policy focused Python suite, 27 tests;
- disposable authenticated Chromium smoke for shell install/restart/transport
  recovery, Settings authorization/isolation/clear, and the Calendar, Chat,
  CRM, Mail and Fitness Coach read models.

The broader fast suite also completed all directly relevant PWA groups. Its
remaining failures were pre-existing and outside this rollout: repository
path/line-size contracts, stale Base Shell source-shape assertions, and a
Storage widget temporary-copy import setup. They were not hidden, waived as
PWA evidence, or expanded into unrelated refactors.

## Controlled rollout

The baseline was healthy with Service Worker v2 enabled, structured data cache
disabled, file cache disabled and 0/8 app gates enabled.

1. Website Studio pilot: the global gate and only the Website Studio app gate
   were enabled. Authenticated registry inspection confirmed the exact scope.
   A live browser cold read seeded IndexedDB; the following navigation painted
   from that cache with the app read transport intentionally blocked and an
   active frame mounted.
2. Eight-adapter cohort: the remaining reviewed app gates were enabled with
   100% workspace and user percentages. Authenticated inspection reported 8/8
   enabled and no unexpected app.
3. Each adapter was exercised live with a cold seed followed by a warm read
   while its app-owned display read transport was blocked: App Store, Calendar,
   Chat, CRM, Fitness Coach, Mail, Storage and Website Studio all passed.
   Storage's home screen intentionally uses `catalog.summary`; its reviewed
   `file-catalog` broker contract was therefore probed directly from the
   authenticated Storage frame without changing user view state.
4. After the final restore and restart, Website Studio repeated the same live
   cold/warm blocked-transport check successfully.

No live records were created, edited or deleted by these rollout probes.

## Rollback drill

The complete bounded PWA rollout block was removed from the service
environment and `maverick-core.service` was restarted. The public configuration
then reported `data_cache=false`, `storage_file_cache=false`; authenticated
registry inspection reported 0 enabled adapters; health remained `ok` and
Service Worker v2 remained available.

The exact approved block was restored and the service restarted again. Final
inspection reported `data_cache=true`, `storage_file_cache=false`, all eight
reviewed adapters enabled, no unexpected adapter, health `ok`, and no systemd
restart loop (`NRestarts=0`).

Immediate stop path: remove the bounded block headed `PWA controlled rollout`
from `/home/ubuntu/projects/maverick-v3/.env`, restart
`maverick-core.service`, and verify `/api/pwa/config` plus the authenticated
`/api/apps` registry. The file-cache flag must not be added until its resource
classification and approval change explicitly.

## Go decision

The controlled structured-data rollout is **go** for this deployment and exact
candidate under the time-bounded release-owner waiver. The performance plan's
P7 rollout/rollback work is complete under that recorded decision. Full 69/69
physical certification is not claimed, and file-byte persistence remains out
of scope and off by policy.
