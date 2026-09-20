# PWA cache — technical closeout, 2026-09-20

## Decision and scope

The product owner asked to finish development autonomously, with simple code
and focused automated checks rather than another manual release exercise.
Technical completion is separate from production promotion. PWA-098 physical
Safari/iOS/Home Screen/Dock testing, a production cohort rollout and an
operational rollback drill are deferred, **not passed**. They do not block this
development closeout or require a task from the user. Existing production
promotion safeguards and default-off private-cache flags are unchanged.

The eight approved app integrations remain in scope. The 2026-09-05 privacy
decision is not reopened, and the 2026-09-06 candidate/device evidence remains
historical rather than certification of today's assets.

## Completed changes

- `653e91f3`: fail-closed unsafe HTTP origin proof, including opaque/malformed
  Origin, scheme/port mismatch and untrusted forwarded headers. Security docs
  now distinguish implemented HTTP/WebSocket controls from remaining reviews.
- `97855222`: replace the flaky persistence-deadline test's sleep with its
  existing injected clock; production runtime code and deadlines are unchanged.
- `543a380b`: People, Companies and Deals reuse CRM's existing display adapter.
  Query changes cancel old reads; same-query refresh preserves rows; changed
  revalidation cannot be overwritten by the initial snapshot; authorization
  denial clears displayed rows. Workflow reads and mutations stay live.
- `70c6e4ec`: include the minimal AbortSignal transport in the checkpoint itself,
  without taking the other agent's timeout policy. The isolated build caught
  this otherwise hidden dependency on a concurrent edit.
- CRM resource revision v2 projects numeric `margin_minor` without broadening
  arbitrary fields or workflow authority. Backend and shell use the same schema.
- The existing disposable-host smoke now asserts actual rows in all three CRM
  views, including deal margin, with **all CRM backend transport blocked**.

No new cache framework, outbox, connectivity mode, release matrix or runtime
feature flag was introduced. Concurrent public-CRM/provider/Chat/Settings work
was not staged into these source commits. Generated artifacts are built from a
pinned export and staged without replacing the shared working-tree builds.

## Verification

Focused suites ran on the integrated working tree. CRM browser checks and the
final smoke also run against the isolated source/artifact export, so a passing
shared-tree check cannot hide a missing committed dependency.

The export uses source baseline `70c6e4ec`, the updated smoke helper and the
CRM/Shell artifacts committed in `12060208`. Other agents' later Chat/Skills
commits are not part of that smoke export; this is scoped PWA evidence, not an
immutable certification of the whole moving branch. Manifest build ids:

- Base Shell: `028efb462d77724d8cea4c8edc68428ad2b0097941512df01af9f700abe6ee13`
- CRM: `0699477aaa87f8e7f06139ec0113e2ba5d20164899ebb66d457227068ffa403a`

The isolated Chromium smoke passed at `2026-09-20T10:55:37.019Z`; the fixture
helper rejects execution without the disposable-host marker. Its stronger CRM
assertions supplement, rather than replace, the unchanged shell recovery,
authorization, cleanup and non-replay checks.

| Focused checks | Result |
| --- | --- |
| Shared cache SDK | 195 passed; typecheck passed |
| Base Shell | 228 passed |
| Worker/build/browser contracts | 17 passed |
| HTTP, ASGI, cache audit/device verifier | 49 passed |
| Runtime finalization | 10 passed; fixed case also repeated three times |
| CRM display schema/conditional revision | 2 passed |
| CRM browser product/display regressions | 8 distinct tests passed |
| Official CRM / Base Shell builds | passed |
| Cache policy/manifest audit, unused imports, diff whitespace | passed |

Chromium on a disposable authenticated host verifies IndexedDB seeding and
warm reads for Calendar, Chat, CRM, Mail and Fitness Coach; the 16-asset standard
shell survives transport loss/restart, keeps its mounted tree and recovers.
Settings diagnostics/clear run through its isolated origin. No live workspace
records, rollout flags or service restart are needed by these checks.

This is not a claim that the entire concurrently edited repository is green.
The earlier broad fast run found unrelated repository path/size contract
failures and was bounded rather than used as a release certificate. Those
files belong to ongoing work and were not refactored or given larger budgets.
Real Safari and physical installed-app behavior remain unverified.
