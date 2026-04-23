# Agents App Porting Plan

This document defines the complete porting plan for the Maverick v2 `agents` app into Maverick v3.

The goal is not to preserve the v2 backend, route, or Mongo shape. The goal is to make `agents` a native v3 app that owns agent definitions, roles, prompt composition, and management UI while using generic v3 core runtime surfaces to execute agents.

## Source And Target

Source app:

- `/home/ubuntu/maverick-v2/apps/agents`

Target app:

- `/home/ubuntu/maverick-v3/apps/agents`

Current v3 state:

- There is no v3 `agents` app yet.
- Core already has app contracts, app mounting, workspace roots, app backend dispatch, a skills service, and early runtime/session models.
- Runtime and inter-agent execution are still generic core concerns and must not be implemented inside the `agents` app.
- Some core runtime surfaces needed for fully usable agents are incomplete and are listed in this plan as required generic core work.

Porting principle:

- Agents owns role documents, agent type definitions, app-specific management UI, prompt previews, app MCP actions, app CLI helpers, app lifecycle hooks, and app-owned workspace data.
- Core owns users, workspaces, app hosting, app registry, provider adapters, runtime sessions, runtime turns, process lifecycle, sandbox and full-access policy, secrets, recovery, and inter-agent orchestration.
- Chat or other user-facing apps may use agents through generic contracts, not through direct source imports from `apps/agents`.
- Agent definitions are app-owned content, not platform core domain models.

## Non-Negotiable Boundaries

- Do not move agent roles or agent type records into `core/`.
- Do not make core depend on `apps/agents`.
- Do not reintroduce v2 global Mongo collections such as `agent_types`, `roles`, or `agent_instances` as core-facing persistence shapes.
- Do not expose v2 routes such as `/api/agents/catalog` or `/api/agent-types` as the final v3 contract.
- Do not copy v2 FastAPI routers into v3.
- Do not keep role instructions that refer to v2 paths, v2 service names, v2 process managers, or `maverick-v2` internals.
- Do not make `chat` import files from `agents`.
- Do not implement app-specific runtime process management inside `agents`.
- Do not add core branches such as `if app_id == "agents"`.

## Boundary With Core And Chat

The intended architecture is:

- `core/` is standalone, headless, and app-agnostic.
- `apps/agents` is standalone and app-owned.
- `apps/chat` is standalone and app-owned.
- Core exposes generic app backend dispatch, app registry, skills catalog, runtime session, runtime turn, and inter-agent surfaces.
- Agents exposes a catalog of role and agent definitions.
- Chat may select an agent definition and launch a generic runtime session with materialized prompt and skill configuration.

There must be no direct contamination between `core`, `chat`, and `agents`:

- core must not import agent role files, agent UI components, or agent-specific service code
- agents may call generic core APIs, but must not reach into provider adapters or runtime internals
- chat may call generic core APIs and app backend endpoints, but must not know agents storage layout
- shared behavior must be added as generic core surface only when another app can use the same contract

## V2 Inventory

The v2 app contains these important files:

```text
apps/agents/
  app.manifest.json
  backend/
    mount.py
    role_registry.py
    routes.py
    service.py
    roles/
      <role_id>/ROLE.md
  frontend/
    agents-panel.tsx
    styles/
      agent-registry.css
      base.css
      chat.css
      layout.css
      main.css
      responsive.css
      versyBrandTokens.css
```

Generated `__pycache__` directories and empty compatibility files are not porting inputs.

## File Classification

| V2 file | Classification | V3 destination |
| --- | --- | --- |
| `app.manifest.json` | rewrite for v3 | `apps/agents/app_contract.json` |
| `backend/service.py` | rewrite for v3 | `apps/agents/backend/service.py`, `store.py`, `models.py` |
| `backend/role_registry.py` | rewrite for v3 | `apps/agents/backend/seeds.py` and role seed assets |
| `backend/routes.py` | rewrite for v3 | `apps/agents/backend/app_backend.py` |
| `backend/mount.py` | rewrite for v3 | `apps/agents/mcp/server.py`, `apps/agents/cli/app_cli.py` |
| `backend/roles/*/ROLE.md` | port with v3 review | `apps/agents/roles/*/ROLE.md` |
| `frontend/agents-panel.tsx` | rewrite for v3 | `apps/agents/frontend/src/*` |
| `frontend/styles/agent-registry.css` | port as reference | focused v3 app CSS |
| `frontend/styles/base.css` | do not port directly | use app-local minimal base styles |
| `frontend/styles/chat.css` | do not port directly | chat owns chat styling |
| `frontend/styles/layout.css` | port as reference only | focused v3 app layout CSS |
| `frontend/styles/main.css` | port as reference only | focused v3 app CSS |
| `frontend/styles/responsive.css` | port as reference only | responsive rules folded into v3 CSS |
| `frontend/styles/versyBrandTokens.css` | port only if tokens are still product policy | otherwise do not port |

## Role Inventory

The v2 app includes 17 role documents:

- `agent-builder`
- `backend-systems-engineer`
- `business-intelligence-strategist`
- `ceo-business-chief-of-staff`
- `cfo-strategist`
- `cmo-strategist`
- `code-review-auditor`
- `company-os-orchestrator`
- `dynamic-product-price-researcher`
- `frontend-design-engineer`
- `general-operator`
- `piero-linkedin-content-os`
- `platform-verifier`
- `role-creator`
- `server-coding-engineer`
- `versy-design-analyst`
- `versy-media-creative-direction`

The v3 port should seed all 17 roles and create an initial usable `agent_type` for each role. V2 seeded only a smaller subset of default agent types, but the v3 product requirement is to have all agents available to manage and use.

Every role document must be reviewed before import:

- remove stale v2 service names
- replace v2 filesystem paths with v3 paths where appropriate
- remove references to deprecated backend wrappers
- remove references to v2 Mongo-specific internals
- preserve domain intent, operating mode, and useful skill guidance
- keep role instructions as source-managed seed assets, not as hardcoded Python strings

## Target App Structure

Recommended target layout:

```text
apps/agents/
  app_contract.json
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  backend/
    app_backend.py
    models.py
    prompts.py
    seeds.py
    service.py
    store.py
    validation.py
  cli/
    app_cli.py
  frontend/
    index.html
    src/
      main.tsx
      App.tsx
      api/
        agentsBackend.ts
        coreRuntime.ts
        schemas.ts
      components/
        AgentTypeEditor.tsx
        AgentTypeList.tsx
        CommonPromptEditor.tsx
        InstanceList.tsx
        PromptPreview.tsx
        RoleEditor.tsx
        RoleList.tsx
        SkillPicker.tsx
      hooks/
        useAgentCatalog.ts
        useAgentInstances.ts
        useAgentMutations.ts
        usePromptPreview.ts
        useSkillCatalog.ts
      lib/
        agentForms.ts
        agentPrompt.ts
        agentTypes.ts
        executionModes.ts
      styles/
        main.css
        agents.css
        forms.css
  hooks/
    health_check.py
    install.py
    migrate.py
  mcp/
    server.py
  roles/
    <role_id>/
      ROLE.md
  skills/
    agents-ops/
      SKILL.md
```

This structure should stay small. If a file approaches roughly 250 to 300 lines, split by responsibility.

## App Contract

`apps/agents/app_contract.json` should define:

- app id `agents`
- display name `Agents`
- app-owned frontend mount under `/apps/agents/`
- backend entrypoint `apps/agents/backend/app_backend.py`
- MCP entrypoint `apps/agents/mcp/server.py`
- CLI entrypoint `apps/agents/cli/app_cli.py`
- lifecycle hooks for install, health check, and migrate
- workspace data namespace `agents`
- app capability names for catalog management and agent launch

Recommended source distribution:

- ship the app as a built-in sealed app
- keep workspace data mutable
- allow role and agent type edits through app data, not through app source edits

If product policy later requires workspace-specific app source customization, use the v3 app source fork model explicitly. Do not make source mutability implicit.

## Workspace Data Model

Recommended app-owned storage:

```text
workspaces/<workspace_id>/data/agents/
  common_prompt.md
  roles/
    <role_id>/
      ROLE.md
  agent_types.json
  agent_instances.json
```

`common_prompt.md` stores the workspace-level base prompt.

Role records should be stored as markdown with frontmatter so they remain readable, reviewable, and easy to export.

`agent_types.json` stores normalized agent type definitions:

```json
{
  "agent_types": [
    {
      "id": "agent-type-server-coding-engineer",
      "name": "Server Coding Engineer",
      "description": "Backend and platform implementation agent.",
      "role_id": "server-coding-engineer",
      "codex_skill_ids": [],
      "default_execution_mode": "sandbox",
      "execution_mode_policy": "selectable",
      "trace_verbosity": "verbose",
      "enabled": true,
      "created_at": "iso",
      "updated_at": "iso"
    }
  ]
}
```

`agent_instances.json` stores app-owned instance metadata only:

```json
{
  "instances": [
    {
      "id": "agent-instance-id",
      "name": "Readable instance name",
      "agent_type_id": "agent-type-id",
      "status": "idle",
      "runtime_session_id": null,
      "created_at": "iso",
      "updated_at": "iso"
    }
  ]
}
```

Live runtime process state belongs in core. The agents app may store references to runtime sessions, but must not own runtime lifecycle internals.

## Backend Actions

The v3 app backend should expose JSON actions through the generic app backend dispatch endpoint.

Required actions:

- `catalog`
- `list_roles`
- `get_role`
- `create_role`
- `update_role`
- `delete_role`
- `list_agent_types`
- `get_agent_type`
- `create_agent_type`
- `update_agent_type`
- `delete_agent_type`
- `get_common_prompt`
- `set_common_prompt`
- `preview_prompt`
- `list_instances`
- `create_instance`
- `update_instance`
- `delete_instance`

Runtime-dependent actions:

- `start_instance`
- `stop_instance`
- `send_message_to_instance`
- `delegate_to_agent`

The runtime-dependent actions should only be implemented once core exposes a generic runtime invocation contract. Until then, the backend can validate definitions and return a clear unsupported capability result.

## MCP Surface

The v3 app should provide an MCP server with a `maverick_agents_app` tool.

Recommended actions:

- `catalog`
- `list_roles`
- `get_role`
- `create_role`
- `update_role`
- `delete_role`
- `list_agent_types`
- `get_agent_type`
- `create_agent_type`
- `update_agent_type`
- `delete_agent_type`
- `get_common_prompt`
- `set_common_prompt`
- `preview_prompt`
- `list_instances`
- `create_instance`
- `start_instance`
- `stop_instance`
- `send_message`

The MCP tool must use the same service layer as the backend and CLI. It must not duplicate persistence or prompt composition logic.

## CLI Surface

The CLI should support local inspection and maintenance:

- `catalog`
- `seed`
- `list-roles`
- `list-agent-types`
- `export`
- `import`
- `validate`
- `preview-prompt`

The CLI is not a separate product surface. It is an operator and test helper for the app-owned data.

## Prompt Composition

Prompt preview must be deterministic and test-covered.

Prompt composition order:

1. workspace common prompt
2. role instructions
3. agent type metadata
4. assigned skill summaries or skill ids
5. runtime execution policy notes, when needed

The composed prompt should be returned as structured sections as well as rendered text:

```json
{
  "sections": [
    {
      "id": "common_prompt",
      "title": "Common Prompt",
      "content": "..."
    }
  ],
  "rendered": "..."
}
```

This allows the frontend to show prompt previews without parsing raw text.

## Frontend Requirements

The first v3 frontend should provide:

- searchable role list
- role editor
- searchable agent type list
- agent type editor
- common prompt editor
- prompt preview panel
- skill picker
- execution mode controls
- instance list
- create instance action
- start or open runtime action when core supports it

Design constraints:

- keep the first screen as the actual management experience, not a marketing page
- avoid nesting cards inside cards
- keep controls dense and clear
- use icons for commands where appropriate
- do not expose implementation instructions as in-app explanatory copy
- keep text fitting on mobile and desktop

The v2 `agents-panel.tsx` should be treated as product reference, not as source to copy.

## Core Gaps Required For Full Agent Use

The following generic core surfaces are required before agents are fully usable.

### Runtime Launch Configuration

Core runtime needs a generic launch contract that can accept:

- materialized system prompt
- selected provider
- requested execution mode
- selected skill ids
- workspace id
- optional parent runtime session
- optional app-owned source reference

This contract must not mention `agents` directly.

### Skills Catalog API

The frontend needs a generic way to list enabled workspace skills.

Core already has skill catalog service code, but the product needs an app-facing API surface that can be called by mounted apps.

### App-To-Core Invocation

The agents backend and MCP server need a controlled way to request runtime operations from core.

This should be a generic app-host capability or core service invocation surface, not direct imports of runtime internals and not localhost HTTP hacks.

### Inter-Agent Delegation

Full delegation depends on the generic inter-agent runtime model:

- parent-child session links
- message queues
- status propagation
- cancellation
- retry and reconciliation
- workspace policy enforcement

Agents can expose delegation controls only after the generic core model exists.

### Built-In App Discovery

If `agents` should be enabled by default, the platform should avoid adding more hardcoded built-in app ids. Built-in discovery or app registry seeding should be driven by contracts and platform configuration.

## Implementation Phases

## Implementation Checklist

- [x] Phase 1: Architecture and tasklist updates
- [x] Phase 2: Contract and skeleton
- [x] Phase 3: Store and seed data
- [x] Phase 4: Backend service
- [x] Phase 5: MCP and CLI
- [x] Phase 6: Frontend
- [x] Phase 7: Generic core runtime work
- [x] Phase 8: Agent use flow
- [x] Phase 9: Integration and verification

### Phase 1: Architecture And Tasklist

- Add the agents porting decision to the implementation tasklist.
- Update architecture docs if the core/app boundary changes.
- Confirm `agents` is app-owned content and not core domain.

### Phase 2: Contract And Skeleton

- Create `apps/agents/app_contract.json`.
- Add backend, frontend, hooks, MCP, CLI, roles, and skills directories.
- Add minimal health and install hooks.
- Add tests proving the app contract is discoverable and workspace data is under `data/agents`.

### Phase 3: Store And Seed Data

- Implement app-owned store.
- Implement role markdown parser and writer.
- Implement `agent_types.json` read/write validation.
- Seed all 17 role documents after v3 cleanup.
- Seed one agent type per role.
- Add tests for path safety, seed idempotence, and malformed role documents.

### Phase 4: Backend Service

- Implement backend action dispatcher.
- Implement role CRUD.
- Implement agent type CRUD.
- Implement common prompt read/write.
- Implement prompt preview.
- Add tests for every stable action.

### Phase 5: MCP And CLI

- Implement `maverick_agents_app`.
- Implement CLI commands for list, seed, validate, export, import, and preview.
- Ensure MCP and CLI reuse backend service logic.
- Add smoke tests or command-level tests.

### Phase 6: Frontend

- Create Vite React frontend.
- Implement catalog loading.
- Implement role and agent type management.
- Implement common prompt editing.
- Implement prompt preview.
- Implement skill picker once the generic skill catalog API is available.
- Build the frontend and verify it mounts under `/apps/agents/`.

### Phase 7: Generic Core Runtime Work

- Add generic runtime launch configuration if not already available.
- Add generic skill catalog API if not already available.
- Add app-to-core runtime invocation if backend/MCP needs to start sessions.
- Add tests proving these surfaces are app-agnostic.

### Phase 8: Agent Use Flow

- Create agent instances from agent types.
- Start a runtime session from an agent instance.
- Open or attach the session in chat or another runtime UI.
- Preserve app-owned instance metadata separately from core runtime state.

### Phase 9: Integration And Verification

- Run focused agents app tests.
- Run app contract and built-in app tests.
- Run the official frontend build lifecycle with `maverick app agents frontend build --json`.
- Run unused import check after Python refactors.
- Review diff for stale v2 references.
- Update docs and implementation tasklist in the same change.

## Testing Plan

Recommended focused tests:

- contract discovery for `apps/agents`
- install hook seeds `data/agents`
- seed is idempotent
- all 17 role ids are present
- all seeded agent types reference existing roles
- role parser rejects invalid frontmatter
- path traversal is rejected
- CRUD actions preserve normalized models
- prompt preview composition order is stable
- delete role is rejected while referenced by an agent type
- MCP actions call the same service behavior as backend actions
- CLI validate catches missing role references

Recommended verification commands:

```bash
python3 -m pytest tests/test_agents_app_contract.py
python3 -m pytest tests/test_agents_app_store.py
python3 -m pytest tests/test_agents_app_backend.py
python3 -m pytest tests/test_phase13_builtin_apps.py
python3 scripts/check_unused_imports.py
npm --prefix apps/agents run build
```

The exact test filenames may change during implementation, but the behavior above should be covered.

## Migration From V2 Data

The first v3 implementation should seed clean defaults from source-controlled role assets.

Importing live v2 data is separate work:

- export v2 roles, agent types, common prompt, and selected instance metadata
- normalize ids and references
- reject unsupported v2 runtime state
- import as workspace-owned `data/agents`
- report skipped records with reasons

Do not treat v2 Mongo records as the canonical v3 model.

## Recommended First Milestone

The first useful milestone should deliver:

- v3 `agents` app contract
- app install and health hooks
- workspace-owned agents data store
- all 17 roles seeded
- one seeded agent type per role
- backend catalog and CRUD actions
- MCP catalog and CRUD actions
- prompt preview
- focused tests
- documentation and tasklist updates

This milestone gives Maverick v3 a complete manageable agent catalog. Runtime launch and inter-agent delegation can then be completed through generic core surfaces without contaminating the agents app.
