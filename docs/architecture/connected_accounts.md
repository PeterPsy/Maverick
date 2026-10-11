# Google identity and connected accounts

Core owns federated identity, OAuth consent, personal connected-account metadata,
workspace selections, and credential refresh. App product data remains app-owned.
Google is the initial provider; apps declare `permissions.external_accounts`
with provider declarations containing `capabilities` (currently `calendar`, `gmail`,
`drive`) and optional `replaces_secrets` for manually managed credentials.

The shell offers Google login and service selection, including identity-only
login. Password users can link Google from Connected accounts. An authenticated
link establishes the Google subject's association with the Maverick user. Email
equality alone never links an existing account. New Google registrations create
ordinary members without workspace membership; an administrator assigns access.
No Google flow grants platform administration or workspace membership.

OAuth uses server-side authorization-code exchange, PKCE, a browser-bound,
single-use, expiring state, and verified OpenID claims. Only actually granted
scopes are stored. Login sessions retain the existing platform cookie lifecycle.
Google sign-in and API consent are distinct authorities. OAuth client references
are configured with `MAVERICK_GOOGLE_CLIENT_ID_REF` and
`MAVERICK_GOOGLE_CLIENT_SECRET_REF`; defaults are Core Secrets aliases
`google-oauth-client-id` and `google-oauth-client-secret`. Configure
`MAVERICK_GOOGLE_REDIRECT_URI` as the exact registered HTTPS callback ending in
`/api/auth/google/callback` (localhost HTTP is permitted for development).
No credentials are stored in environment variables, app state, or browser data.
`MAVERICK_GOOGLE_ALLOW_REGISTRATION=0` limits sign-in to identities that have
already been linked; the default allows member registrations awaiting workspace
assignment. Enable the Calendar, Gmail and Drive APIs in the selected Google
project and register the callback on a Web application OAuth client. The client
must have the required consent-screen audience and approved scopes before use.

Each user selects one personal Google account per workspace. App capabilities
are enabled by default for services that user selected, and can be disabled
individually. Declared capability, current membership, user identity, account
ownership, connection status and granted scopes gate every broker request.
Unknown capabilities require a new Core provider capability definition and
consent. Adding an app using an existing capability requires no Google consent.

An invocation-scoped private Unix broker gives apps an opaque capability in place
of a Google access token. Core refreshes credentials and forwards only allowed
provider API paths and methods. Apps never receive Google client secrets, refresh
tokens or access tokens. Broker capability cleanup follows entrypoint cleanup,
including streaming. Google disconnect revokes local broker authority immediately;
Google's combined consent may also be revoked explicitly. App disabling is local
and never revokes the shared Google token.

App invocations using personal accounts receive an app-owned data subtree under
`data/<app_id>/connected-accounts/<user>/<account>/`. This prevents private Mail,
Calendar and Drive caches from appearing in another workspace member's app.
Existing manually connected app data is retained in its original location; it is
not automatically attributed to a personal Google identity. Disabling use of the
personal connection for an app returns that app to its original data root.
Selected but disconnected accounts retain their private subtree so disconnection
cannot accidentally expose another account's cached data.

Calendar, Mail and Storage project the shared account into their existing domain
connection models and use the SDK broker-aware HTTP transport. CLI and MCP share
the same account selection and execution boundary as mounted HTTP entrypoints.
SDK documentation specifies the declaration and payload for new apps.
App-owned OAuth/connect/disconnect operations direct platform-managed connections
to the central panel. Unattributed workspace background hooks receive no personal
Google authority; a background job must supply a trusted owning user context.

The flow uses a regular web browser, including mobile browsers. Native clients
using embedded webviews need a system-browser authentication handoff; that native
flow is outside this web implementation.

Public Google deployments must configure consent and verification for their
requested scopes; Gmail restricted scopes can require a security assessment.
External Google project administration is an operator prerequisite, not an
automatic side effect of deploying source code.
