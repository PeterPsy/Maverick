# Settings work surface

Settings owns navigation, drafts, feedback and presentation. Identity, workspace
creation, provider selection, runtime cleanup and persistence remain Core-owned;
voice synthesis and conversation learning use the selected owning apps.

## Page and data boundaries

| Page | Initial reads |
| --- | --- |
| Models & providers | Platform `section=models` |
| Voice | Platform `section=voice`, then selected synthesis provider |
| PC use | Platform `section=computer-use` |
| Usage | Platform `section=context`, then subscription usage and token history |
| Users & access | Users and workspaces |
| Workspace apps | Context, workspaces, app bindings; registry icons independently |
| App links | Context and app bindings; registry and at most four dependency reads concurrently |
| Conversation learning | Context, then Chat-owned learning data; scheduling model choices independently |
| Sessions | Context and cleanup inventory |
| Cache | Private shell cache diagnostics channel |
| Persistence | Persistence status; dry run/apply only after explicit actions |

`settingsResources.ts` deduplicates pending reads, retains successful data after
a failed refresh, supports resource-local retry, and aborts superseded requests.
An aborted transport cannot publish a late response even if it ignores its
AbortSignal. Workspace changes invalidate cached data and controllers.

## Rendering and drafts

`settingsDom.ts` reconciles keyed nodes. Inputs, text selection, details and scroll
containers survive unrelated updates. A bounded cache retains up to twelve
detached page/user surfaces. Page identities include the workspace, page and
active account; Core's injected frame scope supplies the workspace before any
settings read completes. Workspace transitions unmount chart roots, clear that cache and
the mounted DOM, and invalidate all recorded dirty controls. Rebinding
controls aborts their previous listeners. React chart roots are reused, kept
outside DOM reconciliation, and unmounted when leaving Usage. The chart module
is imported only when Usage is visited.

`settingsDrafts.ts` holds saved voice/routing baselines separately from editable
values. Refreshes preserve dirty values; acknowledgements and discard affect
only the owning section. Operator and synthesis controls follow the same rule.
User mutations consume their authoritative response instead of rereading all
settings. Form actions capture values before disabling controls, communicate
saving/success/error locally, and reject duplicate submissions.

Model binding saves apply Core's returned `agentic_admin` projection to the latest
workspace snapshot as soon as the write is acknowledged. They do not require a
second catalog GET to report success, so an unavailable catalog refresh cannot
roll back an acknowledged switch. Workspace identity and controller generations
still fence late acknowledgements.

Navigation selectors and immediate-save controls declare
`data-settings-controlled`: their value follows controller state on every render.
Model enablement, workspace app enablement and app provider choices show explicit
pending values, lock during the request and roll back to saved values on failure.
App links uses separate read and workspace generations; a refresh cannot orphan
a save, a pre-acknowledgement read cannot replace its result, and an old workspace
completion cannot clear a new save of the same link. Learning discard and successful
acknowledgements clear both controller drafts and the owning DOM draft markers,
including retained pages detached during a save. Native select menus use the
current theme tokens, and primary buttons keep the matching accent text colour.

Models, synthesis, transcription, routing, usage and sessions have separate view
modules. CSS is split by responsibility while preserving the original cascade.
The app owns copies of native Loopino tokens, pre-paint dark/light setup, exact
parent theme/navigation handling, the inner scrolling region and mobile offset.

## Administrative actions

Sessions starts with the current workspace even when Core permits server-wide
cleanup in Default. Server scope requires an explicit selection. Search/status
filters and twenty-row pagination bound rendering. Confirmation names the
scope, selected count, possibly active agents and permanent removal of their
conversations, turns and runtime files. Requests always contain explicit ids.
User deletion and browser cache clearing also use cancellable native dialogs.
Migration dialogs trap focus, support Escape when idle and restore focus to
their opener. Migration feedback reports observed phases without percentage
claims.

## Verification and performance evidence

Run frontend behavioral tests serially with
`npm --prefix apps/settings test -- --maxWorkers=1 --fileParallelism=false`;
run the app fast checks with
`python3 scripts/test_suite.py --app settings --level fast --jobs 1` and Core
settings checks with `python3 -m unittest tests.unit.api.test_settings_api`.
Build mounted assets through `loopino app settings frontend build --json`.

Regression coverage includes continuous sidebar input, late/cancelled reads,
partial failures, retained focus/selection/disclosures/chart islands, draft
acknowledgements, bounded dependency loading, session scope/pagination and form
locking. Desktop/mobile acceptance must inspect the mounted shell, themes,
dialog cancellation, scrolling and clipping without deleting real records.
Learning flow tests use the production `patchSettingsDom` renderer. Regression
checks also cover account A → B → A, mounted workspace resets, failed immediate
saves, refresh/save completion in both orders, discard followed by save/review,
independent ticket filters, and select option contrast in both themes.

Core emits redaction-safe `Server-Timing` composition phases. Browser performance
entries keep the latest `settings.render` and `settings.load.<resource>` duration.
The proposed budgets are 100 ms for local feedback, 200 ms for cached navigation
and one second for a useful initial section under agreed server conditions.
They are targets, not measured percentile claims. A slow general provider projection cannot
block Users, Sessions, Cache or Persistence. PC use reads only its operator catalog. Deployment verification of
new Core projections requires the running backend to load the changed code.

After the 2026-10-12 backend restart, an authenticated browser read of
`section=context` returned no model/provider catalogs or session inventory.
One direct request took 101 ms from browser request to response. In mounted
Learning, a context read took about 150 ms while its independent model catalog
read took 3.74 seconds. These are individual network observations, not server
composition timings or percentile measurements. The rebuilt main entry is
178,743 bytes (47,930 bytes gzip), with charts still in a separate module.
