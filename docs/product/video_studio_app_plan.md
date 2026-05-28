# Video Studio App Plan

Status: planning
Date: 2026-05-20

Review update: tightened after implementation review on 2026-05-20. The key
constraints are now explicit: first development is workspace-local, Remotion packages
must be pinned to an approved `4.0.x` version, rendering is asynchronous with bounded
jobs, large media must not be base64-shuttled through ordinary content APIs, and the
final contract must be generated and validated by the active Maverick SDK/parser.

## Goal

Create a new Maverick app for agent-driven video editing with a human-usable frontend.

The app should use Remotion as the composition and rendering engine, but it should not make
Remotion a Maverick core dependency and should not copy the full Remotion monorepo into
Maverick. The product should feel like a Maverick-native video editor:

- agents can create, inspect, edit, and render video projects through MCP and CLI surfaces
- humans can use a mounted frontend to review, edit, preview, and export projects
- all workspace-owned project data lives under `workspaces/<workspace_id>/data/<app_id>/`
- all generated videos and derived media assets are written under workspace storage
- the core only hosts and governs the app through the generic app contract model

Recommended app id: `video-studio`.

Alternative app ids:

- `remotion-studio` if the product should explicitly signal the Remotion engine
- `video-renderer` if the initial scope is render-focused rather than editor-focused

This plan assumes `video-studio` as the app id.

## Source Mode Decision

First implementation mode: `workspace_local`.

Canonical source path while developing:

```text
workspaces/<workspace_id>/apps/<local_app_id>/
```

Canonical data path:

```text
workspaces/<workspace_id>/data/<local_app_id>/
```

For the initial plan, `<local_app_id>` is expected to be `video-studio`. The document may
show `video-studio` in examples for readability, but implementation code must use the
workspace binding's local app id and the `data_root` provided by Maverick entrypoint
payloads. It must not hardcode installation-level source paths or assume that
`public_app_id`, `local_app_id`, and `mount_app_id` are always identical.

When running SDK commands from the workspace root, the SDK may describe the generated
source as `apps/video-studio/` relative to that workspace. The full canonical path is
still `workspaces/<workspace_id>/apps/video-studio/`. If the app is later promoted into
an installation-level built-in/server app, the promoted copy lives under installation
`apps/video-studio/` and the contract distribution must change to `sealed` or
`source_available`.

## Product Shape

`video-studio` should be a mixed Maverick app:

- `frontend`: human video editing workspace
- `backend`: project, asset, render, and export service
- `mcp`: agent tools for structured video operations
- `cli`: smoke checks, batch operations, and automation
- `skills`: operational guidance for agents
- `hooks`: install, migrate, and health checks

The app is standalone. It should not connect to a Remotion-hosted service by default.
It should use Remotion packages locally. Optional cloud rendering can be added later as a
provider mode.

## What To Take From Where

### From Remotion

Use Remotion as an engine, not as the app product.

Primary upstream references:

- GitHub repository: `https://github.com/remotion-dev/remotion`
- Remotion docs: `https://www.remotion.dev/docs`
- Remotion Player docs: `https://www.remotion.dev/docs/player`
- Server-side rendering docs: `https://www.remotion.dev/docs/ssr-node`
- Renderer API docs: `https://www.remotion.dev/docs/renderer/render-media`
- Linux dependencies docs: `https://www.remotion.dev/docs/miscellaneous/linux-dependencies`
- Lambda docs for later cloud rendering: `https://www.remotion.dev/docs/lambda`
- License: `https://github.com/remotion-dev/remotion/blob/main/LICENSE.md`

Use these NPM packages in the app, pinned in
`workspaces/<workspace_id>/apps/<local_app_id>/package.json`:

- `remotion`: React composition primitives and runtime helpers
- `@remotion/player`: browser preview in the Maverick frontend
- `@remotion/renderer`: local video rendering
- `@remotion/bundler`: bundle a Remotion composition for rendering
- optional later: `@remotion/lambda` for AWS Lambda rendering mode

Version policy:

- target Remotion line: `4.0.x`
- verified NPM version on 2026-05-20: `4.0.464`
- install with exact versions, not ranges
- do not auto-upgrade to Remotion `5.x`
- update within `4.0.x` only after a deliberate dependency review

Initial install command:

```bash
npm install --save-exact remotion@4.0.464 @remotion/player@4.0.464 @remotion/renderer@4.0.464 @remotion/bundler@4.0.464
```

Legal and dependency approval must happen before implementation work is merged, not only
before public release:

- confirm whether Maverick's intended use requires a Remotion company license
- document the accepted Remotion license posture in the app README
- update Maverick's third-party inventory for Remotion packages
- note that Remotion 5.0 has announced license changes and is outside the MVP target

Do not vendor the whole Remotion monorepo into the app.
Do not depend on Remotion's monorepo tooling such as Bun/Turbo for the Maverick app.
The Maverick app should follow the local React/Vite app pattern.

If any example, snippet, test fixture, or asset is copied from the Remotion repository or
documentation, record the origin and license note in the app README and third-party
inventory. Prefer using the published packages and official docs over copying source.

### From Maverick

Use the official App SDK first.

The SDK currently exposes these templates:

- `minimal`
- `frontend-backend`
- `agent-tool`
- `data-app`
- `widget`
- `react-vite`
- `entity-sqlite`

Use `data-app` as the starting template because this product needs frontend, backend,
CLI, MCP, hooks, JSON state, and app-owned workspace data.

Creation flow:

```bash
maverick sdk templates
maverick sdk docs
maverick core cli run core.app-sdk.create --app-id video-studio --template-id data-app --json
maverick core cli run core.app-sdk.validate --app-id video-studio --json
```

Run these commands from the intended workspace context. For a workspace-local app, the
source created by the SDK is workspace-owned material under
`workspaces/<workspace_id>/apps/video-studio/`, not the installation-level app store.

After replacing the scaffold with real behavior:

```bash
maverick core cli run core.app-sdk.register-local --app-id video-studio --json
maverick core cli run core.app-sdk.install-local --app-id video-studio --json
maverick core cli run core.app-sdk.status --app-id video-studio --json
maverick app video-studio frontend build --json
```

If the app is promoted as a built-in/server app later, use the generic app-hosting
promotion and installation path. Do not add app-specific branches in core.

### From Workspace Storage

Input assets should come from workspace storage:

- `storage/uploaded/` for user-uploaded video, image, audio, font, and brand assets
- `storage/generated/` for agent-created images, voiceovers, intermediate clips, captions,
  and final exports

The app should reference files by stable Storage file ids when available. Paths are useful
for navigation, but they should not become the durable identity of a media asset.

Rendered outputs should be written under:

```text
workspaces/<workspace_id>/storage/generated/<local_app_id>/
```

Project and job metadata should remain under:

```text
workspaces/<workspace_id>/data/<local_app_id>/
```

### Large Media Rule

Do not use `file.content.read` or `file.content.write` to base64-transfer large video,
audio, or MP4 payloads through app backend calls.

The implementation must choose one of these authorized large-file strategies before render
work starts:

1. Storage exposes a validated local path or stream surface for enabled backend apps.
2. The backend resolves a Storage file id to metadata, validates the current
   `workspace_relative_path`, verifies it remains under `storage/uploaded/` or
   `storage/generated/`, and gives the renderer only the validated local path.
3. If neither surface exists cleanly, add or document the missing generic Storage
   capability before promising large media rendering.

Rendered outputs should be written to a job-local temporary path first, then atomically
renamed into `storage/generated/<local_app_id>/...`. After the rename, the app must force or
request Storage reconciliation/metadata resolution and persist the resulting stable
`file_id` in the render job. A render job is not `succeeded` until the output exists and
Storage can resolve it.

For small Markdown/text manifests and preview payloads, `file.content.write` remains fine.

## MVP Vertical Slice

The first implementation should be deliberately narrow:

- project create/list/get
- attach one or more assets from Storage
- simple scene editor
- text, image, and video layer basics
- browser preview that renders a nonblank composition through `@remotion/player`
- local MP4 render
- generated output registered/resolved through Storage
- MCP tools for the same project/scene/render actions

Defer until after the vertical slice:

- full multi-track timeline
- advanced captions
- AI voiceover
- advanced template marketplace
- rich agent side panel
- arbitrary Remotion project import
- cloud rendering

## Target User Workflows

### Human Workflow

1. Open `Video Studio` from the Maverick app shell.
2. Create a project or open an existing project.
3. Import workspace assets from Storage.
4. Build or edit scenes on a timeline.
5. Preview the video in-browser through `@remotion/player`.
6. Adjust text, layout, timing, transitions, audio, captions, and export settings.
7. Start a render job.
8. Download or open the generated file from Storage.

The first screen should be the editor/library, not a marketing landing page.

### Agent Workflow

1. Agent receives a request such as: "Create a 45 second launch video from these assets."
2. Agent calls MCP to create a project.
3. Agent imports or references Storage assets.
4. Agent creates script, storyboard, scenes, captions, and timing as structured project data.
5. Agent asks the app to preview or render.
6. Agent inspects render status and output file references.
7. Human opens the same project in the frontend and makes final edits if needed.

Agents should edit a declarative video project model. They should not write arbitrary
Remotion React code in the first implementation.

## Declarative Project Model

The app should persist structured project state instead of exposing raw Remotion source as
the primary editing surface.

Suggested project model:

```json
{
  "schema_version": "1",
  "project_id": "launch-video",
  "revision": 1,
  "title": "Launch Video",
  "created_at": "2026-05-20T00:00:00Z",
  "updated_at": "2026-05-20T00:00:00Z",
  "created_by": {
    "type": "user",
    "id": "user_123"
  },
  "settings": {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "duration_frames": 1350,
    "background": "#101010"
  },
  "timeline": {
    "tracks": [
      {
        "track_id": "main",
        "kind": "visual",
        "items": []
      },
      {
        "track_id": "audio",
        "kind": "audio",
        "items": []
      }
    ]
  },
  "scenes": [
    {
      "scene_id": "intro",
      "name": "Intro",
      "start_frame": 0,
      "duration_frames": 120,
      "layers": [
        {
          "layer_id": "headline",
          "kind": "text",
          "text": "Introducing Maverick",
          "style": {
            "font_size": 72,
            "color": "#ffffff"
          },
          "layout": {
            "x": 120,
            "y": 180,
            "width": 1680,
            "height": 160
          }
        }
      ]
    }
  ],
  "assets": [
    {
      "asset_id": "logo",
      "kind": "image",
      "storage_file_id": "file_123",
      "workspace_relative_path": "storage/uploaded/brand/logo.png"
    }
  ],
  "exports": []
}
```

The Remotion composition should be generated from this model by app-owned renderer code.
This keeps agent operations safe, reviewable, and testable.

Before implementation, finalize the schema in `backend/models.py` and mirror the TypeScript
types used by the frontend/renderer. Required schema decisions:

- use `revision` or `etag` for optimistic concurrency between humans and agents
- make patch operations granular instead of relying on one broad `project.update`
- decide whether coordinates are pixel-based, normalized, or both; MVP should use pixels
  with explicit project width/height
- define layer kinds: `text`, `image`, `video`, `audio`, `caption`, `shape`
- define allowed fit modes: `contain`, `cover`, `stretch`, `none`
- define trim, crop, opacity, volume, mute, and playback-rate fields
- define transition and easing allowlists instead of free-form strings
- return deterministic validation errors that agents can read and repair

Suggested patch actions:

- `project.patch_metadata`
- `scene.create`
- `scene.patch`
- `scene.reorder`
- `layer.create`
- `layer.patch`
- `layer.delete`
- `asset.attach`
- `render.start`

## App Contract Direction

The contract should declare only real surfaces.

Suggested contract shape:

```json
{
  "app_id": "video-studio",
  "contract_version": "1.0",
  "name": "Video Studio",
  "version": "0.1.0",
  "description": "Agent-driven video editing and rendering inside a Maverick workspace.",
  "publisher": "maverick",
  "minimum_core_version": "0.1.0",
  "provides": [
    {
      "interface": "video.project",
      "version": "1",
      "description": "Workspace video projects and editing state.",
      "surfaces": ["backend", "cli", "mcp", "reference", "view"]
    },
    {
      "interface": "video.render",
      "version": "1",
      "description": "Workspace video render jobs and generated exports.",
      "surfaces": ["backend", "cli", "mcp"]
    }
  ],
  "requires": [
    {
      "alias": "workspace-files",
      "interface": "file.catalog",
      "version": "^1",
      "required": true,
      "cardinality": "one",
      "description": "Workspace file catalog used to select video, image, audio, and generated assets."
    },
    {
      "alias": "asset-read",
      "interface": "file.content.read",
      "version": "^1",
      "required": true,
      "cardinality": "one",
      "description": "Workspace file content read surface used for bounded metadata, text, and small preview reads; large media rendering must use the approved large-file strategy."
    },
    {
      "alias": "export-write",
      "interface": "file.content.write",
      "version": "^1",
      "required": true,
      "cardinality": "one",
      "description": "Workspace file content write surface used to save rendered exports."
    }
  ],
  "distribution": {
    "mode": "workspace_local",
    "source_access": "editable"
  },
  "presentation": {
    "frontend_role": "workspace"
  },
  "capabilities": {
    "mcp_tools": [
      "video_studio_project_create",
      "video_studio_project_list",
      "video_studio_project_get",
      "video_studio_project_patch",
      "video_studio_asset_attach",
      "video_studio_scene_create",
      "video_studio_scene_update",
      "video_studio_timeline_update",
      "video_studio_template_list",
      "video_studio_template_apply",
      "video_studio_render_start",
      "video_studio_render_status",
      "video_studio_render_cancel",
      "video_studio_reference_manifest",
      "video_studio_reference_search",
      "video_studio_reference_resolve",
      "video_studio_reference_summarize"
    ],
    "cli_commands": ["video-studio"],
    "skills": ["video-studio-ops"],
    "views": ["video-studio"],
    "data_events": [
      {
        "resource": "projects",
        "description": "Emitted when video projects or timelines change."
      },
      {
        "resource": "render-jobs",
        "description": "Emitted when render jobs are created or updated."
      }
    ],
    "view_surfaces": [
      {
        "view_id": "video-studio",
        "display_name": "Video Studio",
        "entity_types": ["video_project", "render_job"],
        "state_actions": [
          {
            "action": "view_filter",
            "standard": true,
            "description": "Read the current Video Studio library view filter."
          },
          {
            "action": "set_view_filter",
            "standard": true,
            "description": "Set Video Studio project and render-job filters."
          }
        ],
        "supports_custom_view": true,
        "supports_filter_refinement": true
      }
    ],
    "reference_entities": [
      {
        "entity_type": "video_project",
        "display_name": "Video Project",
        "searchable": true,
        "resolvable": true,
        "summarizable": true,
        "deep_link_supported": true
      },
      {
        "entity_type": "render_job",
        "display_name": "Render Job",
        "searchable": true,
        "resolvable": true,
        "summarizable": true,
        "deep_link_supported": true
      }
    ]
  },
  "entrypoints": {
    "mcp": "mcp/server.py",
    "cli": "cli/app_cli.py",
    "backend": "backend/app_backend.py",
    "frontend": "frontend/dist",
    "skills_root": "skills",
    "hooks": {
      "install": "hooks/install.py",
      "migrate": "hooks/migrate.py",
      "health_check": "hooks/health_check.py"
    }
  },
  "storage": {
    "storage_kind": "json",
    "data_schema_version": "1",
    "primary_paths": [
      "data/video-studio/state.json",
      "data/video-studio/projects/",
      "data/video-studio/jobs/",
      "data/video-studio/templates/",
      "data/video-studio/cache/"
    ],
    "indices": {
      "kind": "file_based"
    },
    "supports_export": true,
    "supports_import": true,
    "supports_migrations": true
  },
  "permissions": {
    "secrets": {
      "read": [],
      "write": []
    },
    "network": {
      "outbound": []
    },
    "runtime": {
      "create_sessions": false,
      "cleanup_sessions": false
    },
    "host": {
      "telemetry": false
    }
  },
  "compatibility": {
    "workspace_modes": ["sandbox"]
  }
}
```

The real contract must also include the standard lifecycle, hook timeout, health,
failure-semantics, and rollback sections required by the active app contract parser.
The JSON above is an implementation direction, not a complete file to paste blindly.
Generate the initial contract through the SDK and then modify only fields accepted by the
active parser. Do not manually invent a final contract from this excerpt.
Service code must use the `data_root`, `public_app_id`, and `local_app_id` supplied by
Maverick entrypoint payloads rather than deriving paths from the literal strings in this
example.

If the app is added as a built-in installation-level app instead of a workspace-local
project, change `distribution.mode` to `sealed` or `source_available` and follow the
generic server app installation flow.

## Proposed Source Layout

Use the SDK-generated app tree, then converge toward this shape:

```text
workspaces/<workspace_id>/apps/<local_app_id>/
  app_contract.json
  README.md
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  backend/
    app_backend.py
    models.py
    service.py
    store.py
    renderer_bridge.py
    asset_refs.py
    errors.py
  cli/
    app_cli.py
    command_schemas.json
  frontend/
    index.html
    src/
      main.tsx
      api/
      components/
      editor/
      library/
      preview/
      timeline/
      styles/
  hooks/
    install.py
    migrate.py
    health_check.py
  mcp/
    server.py
    tool_schemas.json
  renderer/
    src/
      entry.tsx
      composition.tsx
      render.ts
      project-to-composition.ts
      schema.ts
  skills/
    video-studio-ops/
      SKILL.md
  tests/
    test_video_studio_app.py
```

`renderer/` is app-owned Node/TypeScript code. It should be small and purpose-built.
It is not a clone of the Remotion repository.
It should normally use the app root `package.json` and `node_modules` rather than a
second nested package manager setup.

If the app is later promoted to a built-in/server app, this same source tree is copied by
the generic promotion flow into installation-level `apps/video-studio/`; development
should not start by editing installation-level app store source unless the explicit
decision is to build it as a built-in from day one.

## Workspace Data Layout

Runtime data for one workspace:

```text
workspaces/<workspace_id>/data/<local_app_id>/
  state.json
  projects/
    <project_id>.json
  jobs/
    <job_id>.json
    <job_id>.log
  templates/
    built_in_index.json
    workspace_index.json
  cache/
    bundles/
    frames/
```

Generated media:

```text
workspaces/<workspace_id>/storage/generated/<local_app_id>/
  projects/
    <project_id>/
      exports/
        <render_id>.mp4
      thumbnails/
        <render_id>.png
      captions/
        <render_id>.vtt
```

The app should never store raw secrets or provider credentials in `data/<local_app_id>/`.
Cloud render credentials, if added, must be delivered through the platform secret system.

## Backend Responsibilities

The backend should be the source of truth for app behavior.

Suggested backend actions:

- `project.create`
- `project.get`
- `project.list`
- `project.patch_metadata`
- `project.delete`
- `asset.attach`
- `asset.detach`
- `timeline.update`
- `scene.create`
- `scene.update`
- `scene.delete`
- `layer.create`
- `layer.patch`
- `layer.delete`
- `template.list`
- `template.instantiate`
- `render.start`
- `render.status`
- `render.cancel`
- `render.list`
- `export.resolve`

Implementation rules:

- parse JSON stdin/stdout through the SDK runtime helpers where available
- route actions in `app_backend.py`
- keep persistence in `store.py`
- keep business logic in `service.py`
- keep Remotion process launching in `renderer_bridge.py`
- validate all ids and all workspace-relative paths
- reject path traversal
- reuse the same service layer from backend, CLI, and MCP

## Renderer Worker

The renderer worker should be app-owned Node/TypeScript code.

It receives a normalized render request:

```json
{
  "job_id": "job_123",
  "project_path": "/workspace/data/<local_app_id>/projects/project.json",
  "output_path": "/workspace/storage/generated/<local_app_id>/projects/project/exports/job_123.mp4",
  "composition_id": "main",
  "codec": "h264",
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "duration_frames": 1350
}
```

It should:

1. load the project JSON
2. validate schema
3. generate the Remotion composition from the declarative model
4. bundle the composition
5. render with `@remotion/renderer`
6. write progress updates to the job status file
7. write the final output into workspace generated storage

For MVP, use local rendering only.

### Async Render Job Model

`render.start` must create an asynchronous job and return a job id. It should not depend on
a long HTTP/backend request staying open until the MP4 is complete.

Required job states:

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

Each job record should contain:

- `job_id`
- `project_id`
- `project_revision`
- `status`
- `created_at`
- `started_at`
- `finished_at`
- `requested_by`
- `progress`
- `output_workspace_relative_path`
- `output_file_id`
- `error_code`
- `error_message`
- `log_path`
- `temp_dir`
- `renderer_pid` or process handle metadata when available

Concurrency and locking rules:

- allow only one active render per project for MVP
- enforce a workspace render concurrency limit
- persist a lock record before launching the worker
- release locks on `succeeded`, `failed`, and `cancelled`
- include stale-lock recovery in health or repair work

Process and cancellation rules:

- launch the Node renderer in a process group where the platform allows it
- pass a minimal environment; do not inherit secrets or full operator env by default
- use Remotion's cancellation support, such as `cancelSignal`, for cooperative cancel
- also terminate the worker process group on hard cancel/timeout
- persist bounded logs and avoid leaking environment variables

Render options that must be set deliberately:

- `concurrency`: bounded by workspace policy and host capacity
- `timeoutInMilliseconds`: finite timeout for render waits
- `cancelSignal`: wired to `render.cancel`
- browser log handling: bounded and redacted

Output rules:

- render into a job temp directory
- write final media to a `*.partial` or temp path first
- atomically rename into the final generated Storage path
- resolve the final output through Storage and persist the stable `file_id`
- mark the job `succeeded` only after output resolution succeeds

Cleanup rules:

- keep final output and bounded job metadata
- clean bundle/frame/temp cache after success or failure according to retention policy
- keep enough failure logs to debug
- provide a later cleanup action for old render jobs and caches

Later provider modes:

- `local`: default renderer using local Chromium/FFmpeg stack
- `lambda`: optional AWS Lambda mode using `@remotion/lambda`
- `remote`: future generic render provider interface if Maverick introduces one

## Frontend Responsibilities

The frontend should be a real editor, not a landing page.

Recommended first screen:

- left rail: projects and asset library
- center: preview canvas/player
- bottom: timeline
- right panel: layer inspector and render settings
- top bar: save, undo/redo if implemented, preview, render
- agent panel: shows suggested changes, generated storyboard, and render actions

Initial controls:

- create/open project
- attach assets from Storage
- add scene
- add text layer
- add image layer
- add video layer
- add audio layer
- trim start/end
- reorder scenes
- edit duration
- edit text, colors, size, position
- preview
- start render
- inspect render status
- open generated output

Frontend should call:

```text
/api/apps/video-studio/backend
```

The frontend should react to app data-change events when backend, CLI, or MCP operations
modify project or job state.

## MCP Surface

MCP tools are the agent-facing product surface.

Suggested tools:

- `video_studio_project_create`
- `video_studio_project_list`
- `video_studio_project_get`
- `video_studio_project_patch`
- `video_studio_asset_attach`
- `video_studio_scene_create`
- `video_studio_scene_update`
- `video_studio_timeline_update`
- `video_studio_template_list`
- `video_studio_template_apply`
- `video_studio_render_start`
- `video_studio_render_status`
- `video_studio_render_cancel`
- `video_studio_reference_manifest`
- `video_studio_reference_search`
- `video_studio_reference_resolve`
- `video_studio_reference_summarize`

MCP tools should accept structured arguments, not free-form edit instructions only.
Natural-language planning can happen in the agent, but the app should receive validated
operations.

## CLI Surface

Expose one app CLI command group: `video-studio`.

Suggested subcommands:

```text
video-studio projects list
video-studio projects get --project-id <id>
video-studio projects create --title <title>
video-studio render start --project-id <id>
video-studio render status --job-id <id>
video-studio render cancel --job-id <id>
video-studio health
```

The CLI should be useful for verification and automation, but MCP is the primary agent
editing surface.

## Skills

Add a bundled skill:

```text
workspaces/<workspace_id>/apps/<local_app_id>/skills/video-studio-ops/SKILL.md
```

The skill should instruct agents to:

- discover app MCP/CLI surfaces through scoped Maverick commands
- use Storage file ids for input assets
- create or update projects through MCP
- prefer structured timeline edits over raw code generation
- render only after validating project settings
- report generated output paths and file ids

The skill must not claim authority. Real operations happen through MCP, CLI, and backend.

## Security And Isolation

The first implementation should avoid arbitrary user-authored Remotion code.

Safe MVP rule:

- agents and humans edit declarative project JSON
- app-owned renderer code converts the project model into Remotion components
- no arbitrary `eval`, dynamic imports from workspace files, or user-supplied React code

Reasons:

- Remotion rendering executes JavaScript
- render workers may launch Chromium
- media files may be large
- remote asset URLs can create network and privacy risk
- render jobs can be CPU and memory intensive

Required safeguards:

- validate project schema
- validate layer kinds and styles
- validate ids
- normalize and bound all paths
- reject traversal outside workspace storage/data roots
- reject symlink traversal from validated media paths
- allow only approved MIME/content types for image, video, audio, font, and text assets
- cap resolution, fps, duration, frame count, file size, and concurrent renders
- store raw job logs inside `data/<local_app_id>/jobs/`
- redact secrets and environment values from logs
- default `permissions.network.outbound` to `[]`
- allow remote media URLs only after an explicit product decision and allowlist policy
- keep cloud render secrets outside app data
- pass a minimal environment to Node render workers
- avoid inheriting operator secrets or platform bootstrap variables
- block remote URLs in the renderer for MVP
- do not use browser flags such as `disableWebSecurity`
- bound browser console logs and stack traces
- cap bundle cache, frame cache, and media cache size
- health check Node, Chromium/Chrome, FFmpeg/FFprobe, and installed Remotion package versions

## Licensing

Before implementation is merged, review Remotion's license and approved version line.

The implementation plan should include a legal checkpoint:

- confirm whether Maverick's usage requires a Remotion company license
- confirm the exact approved package versions
- block automatic upgrades beyond approved `4.0.x` versions
- document accepted license terms in the app README
- record Remotion packages in the third-party inventory
- avoid presenting Remotion as Maverick-owned technology

This checkpoint should happen before real implementation is merged, not after public
release preparation.

## Detailed Implementation Plan

### Phase 0: Product Decisions

Decide and document:

- final app id: recommended `video-studio`
- distribution mode for first build: `workspace_local` while developing
- later distribution mode: `sealed` or `source_available`
- render mode: local only for MVP
- approved Remotion version: exact `4.0.x`, initially `4.0.464` if still current at start
- legal/license decision before merge
- whether remote asset URLs are allowed: recommended no for MVP
- maximum duration/resolution/fps for MVP
- whether arbitrary Remotion code is supported: recommended no for MVP
- workspace render concurrency limits
- Storage large-file access strategy

Output:

- updated plan if decisions differ from this document

### Phase 1: SDK App Creation

Run:

```bash
maverick core cli run core.app-sdk.create --app-id video-studio --template-id data-app --json
```

Then remove scaffold behavior that does not match the real product.

Output:

- `workspaces/<workspace_id>/apps/video-studio/` source tree
- initial `app_contract.json`
- initial README
- initial frontend/backend/MCP/CLI/hooks files

### Phase 2: Contract First

Edit `app_contract.json` before implementing surfaces.

Declare only:

- frontend
- backend
- CLI
- MCP
- skills
- hooks
- reference entities
- view surface
- storage paths

Run:

```bash
maverick core cli run core.app-sdk.validate --app-id video-studio --json
```

Output:

- valid app contract
- contract smoke test added under app tests

### Phase 3: Data Model And Store

Implement:

- `backend/models.py`
- `backend/store.py`
- path validation helpers
- JSON state initialization
- project CRUD
- granular project patch operations
- render job CRUD
- optimistic concurrency with `revision` or `etag`
- schema version handling

Tests:

- creates app state idempotently
- rejects invalid ids
- rejects path traversal
- rejects symlink traversal
- rejects stale project revisions
- reads/writes project JSON
- reads/writes job JSON

### Phase 4: Remotion Renderer Bridge

Add app-owned renderer package under `renderer/`.

Install packages:

```bash
npm install --save-exact remotion@4.0.464 @remotion/player@4.0.464 @remotion/renderer@4.0.464 @remotion/bundler@4.0.464
```

Implementation:

- `renderer/src/schema.ts`
- `renderer/src/project-to-composition.ts`
- `renderer/src/composition.tsx`
- `renderer/src/entry.tsx`
- `renderer/src/render.ts`
- Python bridge in `backend/renderer_bridge.py`

Tests:

- renderer accepts a minimal valid project
- renderer rejects invalid project JSON
- renderer writes output to a controlled path
- backend marks failed render jobs with useful errors
- render cancellation moves job to `cancelled`
- render timeout moves job to `failed`
- final output write is atomic
- final output resolves to a Storage file id

### Phase 5: Backend Service

Implement `backend/service.py` actions:

- project CRUD
- asset attach/detach
- scene and timeline edits
- render start/status/cancel
- reference manifest/search/resolve/summarize
- view filter state if the app declares a view surface

Backend should return app events for project and job mutations.

Tests:

- backend action responses
- app events emitted on writes
- render job lifecycle status transitions

### Phase 6: MCP And CLI

Implement MCP and CLI as thin adapters over `service.py`.

Add:

- `mcp/tool_schemas.json`
- `cli/command_schemas.json`

Verify after install:

```bash
maverick app video-studio mcp list --json
maverick app video-studio mcp inspect video_studio_render_start --json
maverick app video-studio cli list --json
maverick app video-studio cli inspect video-studio --json
```

Tests:

- declared MCP tools are present
- declared CLI command is present
- MCP and CLI call service behavior

### Phase 7: Frontend Editor

Build the first usable editor:

- project library
- asset picker
- preview player
- scene list
- simple scene editor
- layer inspector
- render panel
- job status panel

Use `@remotion/player` for preview.

Run:

```bash
maverick app video-studio frontend build --json
```

Tests/checks:

- TypeScript build
- Vite build
- mounted frontend loads
- no text overflow in core editor controls
- preview renders a nonblank composition for a minimal project
- MVP does not require a full multi-track timeline or rich agent panel

### Phase 8: Lifecycle Hooks

Implement:

- `hooks/install.py`: create state, directories, built-in template index
- `hooks/migrate.py`: migrate schema versions idempotently
- `hooks/health_check.py`: validate data root, Node availability, package install status, and renderer entrypoint

Tests:

- install idempotent
- migrate idempotent
- health check reports missing renderer dependency clearly

### Phase 9: Registration And Install

For workspace-local development:

```bash
maverick core cli run core.app-sdk.validate --app-id video-studio --json
maverick core cli run core.app-sdk.register-local --app-id video-studio --json
maverick core cli run core.app-sdk.install-local --app-id video-studio --json
maverick core cli run core.app-sdk.status --app-id video-studio --json
```

Verify:

- source exists
- project is registered
- app is installed/enabled
- frontend is mountable
- backend responds
- MCP and CLI discovery work
- render output appears under workspace generated storage

### Phase 10: Documentation

Add or update:

- `workspaces/<workspace_id>/apps/<local_app_id>/README.md`
- skill documentation
- third-party inventory for Remotion packages
- app-specific test docs if needed
- this plan if implementation choices diverge

The README should document:

- purpose
- declared surfaces
- storage ownership
- renderer mode
- security limits
- license note
- SDK validation/install flow

### Phase 11: Verification Loop

Run focused checks:

```bash
maverick core cli run core.app-sdk.validate --app-id video-studio --json
npm --prefix workspaces/<workspace_id>/apps/video-studio run build
python3 -m unittest discover -s workspaces/<workspace_id>/apps/video-studio/tests -p 'test_*.py'
maverick app video-studio frontend build --json
maverick app video-studio cli list --json
maverick app video-studio mcp list --json
```

Required focused test coverage:

- contract smoke check
- project schema validation
- path traversal and symlink traversal rejection
- render cancellation
- render timeout
- atomic output promotion
- Storage file id resolution after render
- MCP schema and CLI schema alignment with contract declarations
- frontend nonblank preview
- frontend controls without text overflow

Full render end-to-end tests that require Chromium/FFmpeg may live in the slow suite.

Then run repository-level checks proportional to touched surface:

```bash
python3 scripts/check_unused_imports.py
python3 scripts/test_suite.py --level fast
git diff --check
```

### Phase 12: Cloud Rendering Later

Do not include cloud rendering in the MVP unless local rendering is already stable.

When adding cloud rendering:

- add a provider setting inside app state
- add secret references for cloud credentials, not raw values
- declare secret logical names in the app contract
- add network allowlist entries only for required cloud endpoints
- add separate health checks for cloud mode
- keep local rendering as the fallback if policy allows

## Open Product Questions

These should be answered before implementation starts:

1. Should the final app id be `video-studio` or `remotion-studio`?
2. Is the first version workspace-local only, or should it be promoted as a built-in app?
3. What maximum video length and resolution should MVP support?
4. Should the MVP allow remote URLs as media assets, or only Storage files?
5. Should AI-generated voiceover and captions be part of MVP or a later integration?
6. Should human users edit at scene level only, or should the first version include a real multi-track timeline?
7. Should arbitrary Remotion project import be supported later as an advanced trusted mode?
8. Which exact Remotion `4.0.x` version and license posture are approved?
9. Which Storage large-file access path is available and policy-approved?
10. What render concurrency and timeout values should apply per workspace?

## Non-Goals For MVP

- full Premiere/DaVinci-level editing
- arbitrary user-supplied React/Remotion code execution
- remote cloud rendering
- collaborative multi-user editing cursors
- plugin marketplace for visual effects
- automatic stock footage search
- direct writes to other apps' data roots
- core changes specific to `video-studio`
- automatic upgrades to Remotion `5.x`
- base64 transfer of large video/audio/rendered media through ordinary backend content calls

## Success Criteria

The first useful version is complete when:

- app source is generated through the SDK
- `app_contract.json` validates
- the app is registered and installed in the target workspace
- humans can create a project, attach assets, preview, and render
- agents can create/edit/render through MCP
- outputs appear in workspace generated storage
- all app-owned data lives under `data/<local_app_id>`
- no app-specific core branch exists
- local render works for a minimal project
- focused tests pass
- frontend builds through the official Maverick frontend build command
- README and skill docs match implemented behavior
- Remotion package versions are exact-pinned and legally approved
- render jobs have bounded async status, cancellation, timeout, logs, and cleanup
- final output has a resolved Storage file id
