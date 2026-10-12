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
detached page/user surfaces. Workspace transitions clear that cache. Rebinding
controls aborts their previous listeners. React chart roots are reused, kept
outside DOM reconciliation, and unmounted when leaving Usage. The chart module
is imported only when Usage is visited.

`settingsDrafts.ts` holds saved voice/routing baselines separately from editable
values. Refreshes preserve dirty values; acknowledgements and discard affect
only the owning section. Operator and synthesis controls follow the same rule.
User mutations consume their authoritative response instead of rereading all
settings. Form actions capture values before disabling controls, communicate
saving/success/error locally, and reject duplicate submissions.

Models, synthesis, transcription, routing, usage and sessions have separate view
modules. CSS is split by responsibility while preserving the original cascade.
The app owns copies of native Maverick tokens, pre-paint dark/light setup, exact
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
Build mounted assets through `maverick app settings frontend build --json`.

Regression coverage includes continuous sidebar input, late/cancelled reads,
partial failures, retained focus/selection/disclosures/chart islands, draft
acknowledgements, bounded dependency loading, session scope/pagination and form
locking. Desktop/mobile acceptance must inspect the mounted shell, themes,
dialog cancellation, scrolling and clipping without deleting real records.

Core emits redaction-safe `Server-Timing` composition phases. Browser performance
entries keep the latest `settings.render` and `settings.load.<resource>` duration.
The proposed budgets are 100 ms for local feedback, 200 ms for cached navigation
and one second for a useful initial section under agreed server conditions.
They are targets, not measured percentile claims. A slow general provider projection cannot
block Users, Sessions, Cache or Persistence. PC use reads only its operator catalog. Deployment verification of
new Core projections requires the running backend to load the changed code.
