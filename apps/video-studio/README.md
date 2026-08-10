# Video Studio

Video Studio is Maverick's installation-level, server-first video editor. The
current app source implements Project IR v1, exact rational time, typed editing
operations, and a persistent SQLite revision engine. It does not yet ingest,
transcode, render, execute FFmpeg, expose a Remotion preview, or provide the
frontend editor.

## Ownership and runtime state

The source artifact is `apps/video-studio/`. It is `source_available` and
`forkable`; it is not a workspace-local project. Source presence does not
install or enable the app. Generic app hosting owns registration, installation,
workspace binding, and the trusted `data_root`.

Each installed workspace owns its business data below:

```text
workspaces/<workspace_id>/data/video-studio/
```

Video Studio never reads another app database or writes business data into
Core/control-plane storage. Media bytes remain Storage-owned and Project IR
uses only governed Storage identity and provider provenance.

## Contract Notes

`app_contract.json` declares schema version 2, the single `video-studio` CLI
command, 16 implemented MCP tools, and data-change resources for `projects`,
`project-metadata`, and `revisions`. Native project interchange is a domain
surface; it is not the generic whole-app lifecycle export/import protocol, so
the lifecycle export/import flags remain disabled. The app remains
sandbox-compatible, has no outbound network or secret permissions, and adds no
Core route.

## Project IR v1

The authoritative schema is
[`schemas/project-ir.v1.schema.json`](schemas/project-ir.v1.schema.json). The
normative field and security profile is documented in
[`docs/project-ir-v1.md`](docs/project-ir-v1.md).

Project IR is declarative, renderer-independent, canonical JSON. It contains no
executable code and does not depend on Remotion or FFmpeg. It models:

- canvas dimensions, rational pixel aspect, background, and allowlisted color
  space;
- rational project frame rate, integer timeline frames, project duration,
  sample rate, and channel layout;
- governed asset identity/provenance, source PTS/time base, and VFR PTS maps;
- ordered typed tracks, clips, layers, source ranges, fixed-point transform,
  crop, fit, opacity, and compositing;
- fixed-point audio gain/pan, mute, channel mapping, fades, and envelopes;
- allowlisted easing, transitions, effects, fonts, and templates;
- safe plain text, captions, markers, groups, and declared relationships.

Canonical serialization sorts object keys, emits UTF-8 JSON without
insignificant whitespace, rejects floats/NaN/non-JSON values, Unicode
surrogates, excessive nesting, and integers outside the portable safe range,
and feeds SHA-256 content addressing. Arrays preserve semantic order.

## Exact time model

Frame rate and source time base are reduced rational pairs. Timeline authority
is always an integer frame; no float is authoritative. Conversion uses integer
rational arithmetic and explicit rounding (`floor`, `ceil`, `toward-zero`, or
`nearest-ties-to-even`). The default boundary policy is nearest with ties to an
even result. See [`docs/project-ir-v1.md`](docs/project-ir-v1.md) for the exact
formulas and A/V drift rules.

The test matrix includes 24000/1001, 30000/1001, 60000/1001, VFR PTS maps,
long timelines, repeated conversions, frame boundaries, and audio sample drift.

## Validation and security

Validation is fail-closed and deterministic. Canonical-byte and collection
complexity limits fail before structural, recursive security, indexing, or
semantic work. Errors shared by the service,
backend, CLI, and MCP contain stable `code`, JSON-pointer `path`, `message`, and
sorted `details`. Validators enforce global ID uniqueness, existing references,
non-negative bounded intervals, source ranges, project containment, same-track
non-overlap, transition handles, ordered keyframes/envelopes, registry schemas,
track/clip compatibility, group acyclicity, and workspace-local provenance.

The IR and recorded batches reject executable expressions/scripts, active
markup, arbitrary shaders, remote/data/file URLs, absolute or traversing host
paths, credentials, shell commands, and direct cross-workspace references.
Configurable limits bound canonical bytes, tracks, clips, layers, keyframes,
effects, transitions, captions, markers, groups, and text characters.

## Typed editing operations

JSON Patch is not a domain API. An ordered batch carries `workspace_id`,
`project_id`, `base_revision_id`, `operation_batch_id`, preconditions, actor,
autosave metadata, ordered operations, and bounded metadata. Implemented
operation types are:

- assets: `asset.add`, `asset.remove`;
- timeline: `timeline.insert`, `timeline.overwrite`, `timeline.move`,
  `timeline.trim`, `timeline.split`, `timeline.ripple_delete`,
  `timeline.ripple_trim`;
- properties: `property.set`, `project.rename`;
- transitions/effects: `transition.add/remove`, `effect.add/remove`;
- keyframes: `keyframe.add/update/remove`;
- captions: `caption.add/update/remove`;
- audio: `audio.envelope.add/update/remove`;
- templates/groups: `template.apply`, `group.group`, `group.ungroup`;
- persistent navigation: `history.undo`, `history.redo`.

Every intermediate operation is pure over a detached document; the completed
batch must change the document and pass full Project IR validation before any
revision is committed. Residual and split clips receive deterministic globally
unique child IDs, relative keyframes are trimmed/rebased, and stale transition,
group, and relationship references are normalized before validation. Derived
clip IDs and source boundaries are deterministic.

## Revision semantics and concurrency

See [`docs/revision-engine.md`](docs/revision-engine.md) for the transaction
contract. In summary:

- revisions are immutable canonical Project IR documents;
- the SHA-256 document digest defines `revision-<digest>` identity;
- `main` has one atomically updated head and a current projection;
- `BEGIN IMMEDIATE` serializes competing SQLite writers;
- a mismatched base fails with `stale_revision_conflict`;
- an operation batch ID is idempotent for identical content and conflicts if
  reused with different content;
- revision, head, projection, navigation, idempotency, autosave, and outbox are
  committed or rolled back together;
- undo/redo move the head among immutable revisions using persistent stacks,
  so both survive process restart;
- native export includes a validated document and digest; import validates the
  envelope, complete IR, workspace confinement, and digest before creating a
  project;
- revision comparison emits a stable path-sorted structural diff.

## SQLite schema and recovery

`data/video-studio/app.db` is at schema version 2. Migration
`0001_foundation.sql` is immutable. `0002_project_revision_engine.sql` adds:

- `project_projections`;
- `project_revision_navigation`;
- `project_operation_batches`;
- `project_autosaves`;
- `project_outbox`.

Migrations are ordered, contiguous, checksummed, idempotent, and transactional.
Connections enforce foreign keys and prefer WAL with a verified delete-journal
fallback. Opening the service reapplies only pending migrations; revision head,
navigation, autosaves, idempotency results, and pending outbox events recover
directly from SQLite after restart.

The app prepares only documented app-owned cache/index/job directories next to
the database. Project IR itself is stored in immutable revision rows; native
export does not introduce arbitrary host paths.

## Official surfaces

Backend JSON stdin/stdout, the `video-studio` CLI command, and the declared MCP
tools all call the same `ProjectService`. Domain actions are:

```text
project.create        project.list          project.get
project.rename        project.duplicate     project.archive
project.restore       revision.get          revision.compare
native.export         native.import         operations.apply
history.undo          history.redo
```

MCP exposes one explicit tool per domain action, named with the
`video_studio_` prefix, plus `video_studio_foundation` and the required common
reference manifest. Inspect `cli/command_schemas.json` and
`mcp/tool_schemas.json` for exact discoverable inputs.

Successful mutations emit declared `maverick.app.data-changed` events for
`projects`, `project-metadata`, and/or `revisions`. A durable app-owned outbox is
written in the same transaction as the corresponding state change.

The governed HTTP sidecar remains foundation-only and read-only. No
app-specific FastAPI route was added to Core.

## Deliberate exclusions

This slice does not implement ingest/transcode, rendering, FFmpeg execution,
Remotion preview, media search, agent proposals, editor UI, Core Jobs changes,
app installation, or app enablement. The existing frontend source/artifact is
unchanged by the Project IR and revision engine.

## SDK Flow

Validate the source through the canonical SDK, then run engineering checks from
the repository root:

```bash
maverick core cli run core.app-sdk.validate --app-root apps/video-studio --json
python3 -m unittest discover -s apps/video-studio/tests -p 'test_*.py'
python3 -m unittest discover -s tests/unit/jobs -p 'test_*.py'
python3 -m compileall core apps/video-studio tests
python3 scripts/check_unused_imports.py
python3 scripts/test_suite.py --level fast
```

Frontend and supply-chain gates run from `apps/video-studio/`:

```bash
npm ci
npm run build
npm test
npm run check:supply-chain
npm run check:ffmpeg
npm run check:vulnerabilities
npm run check:release-artifact -- frontend/dist
```

The release-artifact gate intentionally rejects redistributed compositor or
FFmpeg payloads; see `compliance/README.md` for the reviewed boundary.
