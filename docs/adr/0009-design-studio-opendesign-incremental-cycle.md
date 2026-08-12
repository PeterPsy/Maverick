# ADR 0009: Design Studio OpenDesign Incremental Cycle

Status: Accepted

Date: 2026-08-12

## Context

Design Studio originally treated the OpenDesign daemon, its static Next output,
the OpenDesign version, and the writable data generation as one release. That
kept release cutover safe, but a React or CSS change invalidated and rebuilt the
complete OCI-derived runtime even though neither daemon code nor data changed.

The development loop needs independent web delivery without weakening the
existing artifact, migration, browser-origin, or release gates.

## Decision

OpenDesign has two independently verified installation artifacts:

- a runtime artifact containing the daemon and its native/runtime closure;
- a web overlay containing only the static web output.

The active launch selection is one atomic four-field value:

```text
(runtime_artifact_sha256, web_overlay_sha256, od_version, data_generation)
```

Control metadata uses schema v2 and keeps three complete selections:

- `active`: the selection that may launch;
- `previous_release`: the previous runtime/version/data/overlay selection;
- `previous_web`: the preceding overlay selection for the current
  runtime/version/data tuple.

`previous_web` is either null or differs from `active` only by
`web_overlay_sha256`. It is never inherited across a runtime or data cutover.
Adding a web digest to the old v1 triple is not a valid schema.

Release activation remains migration-driven. It may change runtime, version,
data, and overlay together, updates `previous_release`, clears `previous_web`,
and references the existing migration journal.

Web-only activation has its own strict journal. It atomically changes
`active.web_overlay_sha256`, records the old complete selection in
`previous_web`, and changes only the web activation id and control timestamp.
It must not clone data, execute migrations, change the runtime digest or data
generation, or modify any migration journal. The app requests the generic
scoped sidecar restart capability after cutover. Failed restart or readiness
atomically restores the source selection, restarts it, and records the failed
candidate as `previous_web` for evidence; failure to restore is fail-closed.
If both candidate and rollback restarts fail, the journal remains in the
non-terminal `rollback_restart_pending` state. Recovery retries the rollback
restart and only then records terminal `rolled_back` state.

The daemon is patched once to require `OD_STATIC_DIR`. The launcher resolves
that directory only from a verified overlay under the immutable registry and
passes it explicitly. No embedded-web or "latest" fallback exists.

## Artifact and trust model

Web overlays are materialized under:

```text
apps/design-studio/service/vendor/open-design-web/<web-sha256>/
```

Each directory is real, immutable after publication, and verified file by
file. Its externally pinned contract includes archive and file-manifest
digests, compatible runtime digests and OpenDesign version, upstream commit,
lockfile and toolchain digests, SBOM, license inventory, provenance, and a
signature. The verification trust root is pinned in reviewed Design Studio
source outside the overlay; a public key supplied only by the artifact cannot
authorize that artifact.

Development uses one derivation. A release overlay uses two clean independent
derivations whose canonical file manifests and bytes must match. Persistent
cache keys separate dependency, invariant workspace-output, compatible Next,
and web source/build inputs. Every entry has a content manifest, is protected
by a per-key lock, and is published from staging with atomic rename. A valid
dependency cache skips `pnpm install --frozen-lockfile`; invariant workspace
outputs avoid rebuilding packages unaffected by a React patch. Release
derivations disable dependency and compiled caches independently, so neither
derivation can inherit corrupted or shared cache bytes.

The development command never discovers the shared working tree implicitly.
It requires either explicit repository-relative paths whose bytes are
snapshotted for the run, or an immutable `base_sha`/current-`head_sha` range.
The exact same path set is propagated into the repository changed-suite gate.
Gate selection is compositional but not duplicative: frontend, backend,
runtime, hosting, documentation, and release-only paths select only their
owned gates, and `changed_suite` is reserved for relevant core paths.

## Generic core boundary

Core provides the app-agnostic capability `app.<id>.sidecars.restart`. It is
authorized only for an enabled app binding with declared sidecars. The
capability revokes browser tickets and sessions for that app/workspace, stops
only those sidecars, restarts them, waits for their declared readiness, writes
redaction-safe audit evidence, and emits a scoped runtime/frontend-changed
event. Base Shell remounts only iframe and widget instances owned by the
affected app. Core contains no OpenDesign artifact or migration knowledge.

## Release gates

Diff classification is compositional and conservative. Quick and affected E2E
profiles accelerate development; the final release still requires two clean
derivations, all fourteen product scenarios in two workspaces, restart and
isolation coverage, independent web rollback, a separate migration/rollback
smoke, and one final redaction-safe evidence aggregation.
`npm run test:e2e` aliases the final release profile, never the quick profile.
Release evidence also requires an automatically generated change-to-live
benchmark that mutates a reviewed React patch in isolation, proves different
patch/source/overlay digests with no source/build cache hit, activates through
readiness and the scoped browser-remount event, restores the complete initial
selection, and records separate mutation, build, activation, and restoration
timings. The canonical ceiling is 180 seconds.

## Consequences

- Wrapper, app-backend, web-overlay, and full runtime changes have distinct
  development paths.
- A web-only rollback preserves the runtime process contract and writable data
  bytes while retaining independently reviewable evidence.
- The one-time rollout must publish a daemon that requires `OD_STATIC_DIR` plus
  a canonical overlay before the embedded web path can be removed.
- Release reproducibility remains more expensive than a development overlay
  build by design.
