# P6 built-in effect audit delta — 2026-09-06

Scope: source-level reauthorization of the **CLI/MCP read-effect inventory**,
not provider certification, natural conformance, egress approval, PWA release,
or the independent production security review.

The last inventory update is commit `8e498361`. Its hashes differ from the
reviewed source at `f29d5114` in exactly ten app/surface pairs:
App Store, Calendar, Chat, CRM and Mail, each CLI and MCP. Only App Store's
two descriptors changed; the other differences are executable-closure changes.
All other audited app/surface hashes must remain unchanged.

## Reviewed changes

| App | Executable/descriptor delta | Effect assessment |
| --- | --- | --- |
| App Store | `service.py`, `store.py`, both descriptors | New `pinned_apps.read` returns stored pins without launchable-app repair. `pinned_apps()` uses non-seeding `read_json_state`, not `load_state`. CLI/MCP pass no launchable registry; their existing `pinned_apps.list` is also a business-state read. No mutation event is emitted. HTTP list/repair is not authorized by this inventory. |
| Calendar | `actions.py`, new `pwa_read_model.py` | New HTTP display branch reads bounded event windows or one event and local calendar metadata. It does not invoke OAuth, connection changes or sync. No CLI/MCP enum adds this action. Existing action branches are unchanged. |
| Chat | `service.py` | New HTTP projects display branch uses existing `read_state`, a bounded page and conditional response. No runtime/thread mutation or new CLI/MCP action. |
| CRM | `service.py`, `pwa_read_model.py`, root display schema | Import loads a fixed app-owned JSON schema; new HTTP branch calls local read queries and a closed projection. Existing initialization/CLI/MCP branches are unchanged. No workflow/action authority is admitted by the projection. |
| Mail | `service.py`, `pwa_read_model.py`, root display schema | Import loads a fixed app-owned schema; new HTTP branch reads local mailboxes/threads/messages, never send/OAuth/sync. Known connection credential fields, HTML and raw provider structures are not in the closed schema. No new CLI/MCP action. |

The complete backend/descriptor delta from `8e498361` was inspected; no
entrypoint or app-contract changes occur in these closures. P6 already added
the CRM/Mail root JSON policies and SDK `display_models.py` to TCB coverage.
Those JSON policies are included in both executable-closure digests here.

Display content includes customer data (names, addresses, bodies, CRM records,
custom fields and references). It is **not** public/synthetic by virtue of a
projection or read-effect audit. Arbitrary user text can contain secrets or
injection; source classification, semantic provenance and egress authorization
remain mandatory. A field-filter test is not a general leakage proof.

The SDK reader may create its app-local advisory lock. This is not hidden
business-state seeding/repair. The regression explicitly permits only the
existing state file and `.state.json.lock`, and checks original state bytes.

## Regressions and renewed inventory

`tests.integration.cli_mcp.test_p6_effect_audit_delta` executes both actual
App Store entrypoints repeatedly with absent, valid historical and malformed
pin state, including mutation arguments. It checks preserved state, no repair,
no mutation event and no new business artifact. It also checks that new HTTP
display actions are absent from CLI/MCP descriptors, and every CRM/Mail display
shape excludes unknown object fields and privileged map keys.

The three new regressions passed before renewal. Inventory revision
`2026-09-06-p6-builtin-effects-reviewed-v4` renews **only** the ten reviewed
pairs. The full inventory equality/drift and existing execution/containment
tests must also pass before declaring the deterministic checkpoint green.
Any later descriptor, schema or backend drift invalidates this authority again;
there is no automatic refresh at runtime or bootstrap.
