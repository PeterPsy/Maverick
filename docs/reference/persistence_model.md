# Persistence Model

## Control Plane vs App Data

Maverick separates platform control-plane state from app-owned workspace data.

### Control plane

Control-plane state belongs to the platform core and includes:

- users
- sessions
- workspace registry
- workspace memberships
- governance
- quotas
- app installation and binding state
- runtime token and security metadata
- provider metadata
- secret metadata

### App-owned workspace data

App-owned persistent data belongs under:

```text
workspaces/<workspace_id>/data/<app_id>/
```

Examples:

- chat data
- record-centric data
- memory data
- storage state
- Skills app workspace skill copies

## Workspace Roots

Workspace-owned material belongs under:

```text
workspaces/<workspace_id>/
```

This includes:

- app-owned data
- workspace-local apps
- uploaded files
- generated files
- logs
- runtime session, thread, process, event, turn, and state records

Runtime client message ids are also persisted as workspace-scoped admission records. They cover both ordinary queued turns and messages steered into an existing active turn. A steered message persists `runtime.message.steered` with its client message id and terminal admission status. Before the provider call, the admission is durably marked delivery-uncertain; an explicit provider rejection removes that reservation before the message is queued normally, while a missing acknowledgement remains terminal so a retry cannot duplicate a message that may already have crossed the provider boundary.

Agentic tool state is session-partitioned in `tool_invocations.json` and
`tool_confirmation_grants.json`. Invocation and grant transitions use exact
revision compare-and-set. Complete canonical arguments and results are kept
behind Core-owned opaque private locators; the ledger contains only bounded
shape summaries and a domain-separated HMAC. Confirmation grants are
actor/session/turn/invocation/digest-bound, expire, and transition from active
to consumed once. Deleting a runtime session also deletes both ledger
partitions.

## JSON

The default hosted control-plane persistence path uses JSON collections stored outside `.maverick`:

```bash
MAVERICK_CONTROL_STORE=json
MAVERICK_JSON_CONTROL_STORE_ROOT=data/control-plane/json
```

When JSON is selected, platform-owned control-plane records such as identity, workspace registry, app bindings, provider selections, provider credential bindings, runtime API tokens, and secret metadata/value envelopes use the configured JSON root.

## MongoDB

The hosted control-plane persistence path can use MongoDB instead by setting:

```bash
MAVERICK_CONTROL_STORE=mongo
MAVERICK_MONGODB_URI=mongodb://127.0.0.1:27017/maverick
MAVERICK_MONGODB_DATABASE=maverick
```

For a local MongoDB service without authentication, omit the MongoDB username. If MongoDB authentication is enabled, the URI should not contain the raw password. The installer asks for the password once, stores it in the encrypted bootstrap secret store, and writes only a username plus secret ref:

```bash
MAVERICK_MONGODB_USERNAME=maverick
MAVERICK_MONGODB_PASSWORD_REF=platform:secret-alias/mongodb-password
```

When MongoDB is selected, platform-owned control-plane records such as identity, workspace registry, app bindings, provider selections, provider credential bindings, runtime API tokens, and secret metadata/value envelopes use Mongo collections.

Workspace-scoped runtime history and app-owned workspace data remain under the workspace root unless a later architecture decision introduces a dedicated adapter for those domains.

## Secrets

Maverick does not encrypt the whole control-plane database. It does encrypt secret values through the core secret domain.

The preferred secret-store key configuration is:

```bash
MAVERICK_SECRET_KEY_FILE=<protected-secret-key-file>
MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT=data/bootstrap-secrets
```

`MAVERICK_SECRET_STORE_KEY` is a deprecated development and compatibility fallback. It should not be used for hosted installs.

The same core secret value envelope is used for app/provider/workspace secrets and for platform infrastructure secrets. Pre-adapter secrets that are needed before the configured control-plane adapter is reachable may be stored in a local bootstrap secret store, but they still use the core secret envelope and secret ref grammar.

Admin passwords are identity credentials, not long-lived boot secrets. Live installs require the initial admin password during the installer flow, but the installer writes only the password hash to the selected identity credential collection. Normal startup must not require or reset from a plaintext admin password once the admin user exists. Operator recovery uses `core.identity.reset-admin-password`, writes only a password hash to the identity credential collection, and revokes existing sessions for that user.

Adapter migration is an explicit operator workflow owned by the core persistence surfaces.

HTTP:

- `GET /api/admin/persistence`
- `POST /api/admin/persistence/migrations/dry-run`
- `POST /api/admin/persistence/migrations/apply`
- `POST /api/admin/persistence/restart-backend`

CLI:

- `core.persistence.status`
- `core.persistence.migration-dry-run`
- `core.persistence.migration-apply`

MCP:

- `core.persistence.status`
- `core.persistence.migration.dry_run`
- `core.persistence.migration.apply`

Admin apps such as Settings may expose that workflow, but the core must not import or depend on those apps. A migration is full adapter-to-adapter movement: the core copies every control-plane collection to the target adapter, updates the service environment file when available, and requires a backend restart for cutover. During the running process, the source adapter remains the only mounted adapter; after restart, the target adapter is the only mounted adapter. When the operator requests source cleanup, the core schedules deletion of the old adapter storage only after the restarted backend is healthy on the target adapter.

That does not change the architectural boundary:

- domain models should remain persistence-agnostic
- raw database details should stay inside store adapters

## First Public Release Position

Persistence is adequate for evaluation and development review, but not yet a finished production story.

The public docs should continue to treat production hardening and secret handling as incomplete work.
