# Design Studio Native OpenDesign Architecture

Status: Implemented and accepted

Date: 2026-08-28

## Purpose

This document defines the active relationship between Maverick, Design Studio,
OpenDesign, Maverick Chat, and the models installed in Maverick.

The product decision is to use OpenDesign as a complete upstream product inside
Maverick rather than reproduce, hide, or replace parts of it with Maverick-owned
UI and runtime behavior.

In the implemented architecture:

- Design Studio hosts a complete upstream OpenDesign installation;
- the native OpenDesign UI, chat, projects, tools, Design Systems, history, and
  future upstream features remain available;
- OpenDesign may use API and CLI models installed in Maverick, but invokes them
  without Maverick agent context or behavior;
- the global Maverick Chat remains a separate general-purpose orchestrator;
- a Maverick agent may explicitly delegate a design task into a native
  OpenDesign conversation and supply the context it has selected for that task;
- OpenDesign remains authoritative for the design conversation and its outputs.

The checked-in Design Studio implementation follows this architecture. The
rollout steps below are retained as an implementation and verification record.

## Non-Negotiable Zero-Modification Boundary

The OpenDesign package launched by Design Studio must be an official upstream
distribution and must remain unchanged. "Inside Maverick" means that Maverick
starts and hosts that distribution; it does not mean that Maverick changes the
product.

Maverick may:

- select, verify, install, start, stop, and update an official OpenDesign
  package;
- give it a workspace-scoped data directory and an isolated browser origin;
- authenticate the user at the outer hosting boundary;
- configure standard provider endpoints or native CLI profiles;
- call supported public OpenDesign APIs from the external Delegation Bridge;
- return native OpenDesign deep links to the user.

Maverick must not:

- patch OpenDesign source, binaries, web assets, styles, or runtime code;
- build or overlay a custom OpenDesign UI;
- hide, unmount, replace, or reproduce native OpenDesign features;
- intercept or replace native OpenDesign chat, run, model, project,
  conversation, settings, or update behavior;
- inject Maverick code into the OpenDesign browser application;
- read or write OpenDesign's private database directly; or
- require a Maverick-specific OpenDesign fork.

There are exactly two external integration boundaries:

1. **Model Access Bridge:** a technical catalog and transport that makes
   Maverick-configured API and CLI models available to OpenDesign without any
   Maverick prompt, memory, persona, skill, tool, Chat history, or agent
   runtime.
2. **Delegation Bridge:** an external client that inserts one explicit,
   visibly attributed brief and authorized attachments into a native
   OpenDesign conversation through a supported public API.

Only the Delegation Bridge carries Maverick-authored semantic content, and that
content is limited to the delegated visible brief and authorized attachments.
Hosting metadata, authentication, credentials, process control, streaming,
cancellation, model catalog entries, and correlation ids are technical data,
not additional model context.

## Relationship to the Retired Implementation

The retired implementation removed or replaced parts of the native OpenDesign
experience, used Maverick Chat as the Design Studio composer, and translated
OpenDesign runs into Maverick runtime sessions. It is documented historically
in:

- `docs/architecture/design_studio_runtime_bridge.md`;
- `docs/architecture/design_studio_data_generations.md`; and
- `docs/adr/0009-design-studio-opendesign-incremental-cycle.md`.

This implementation superseded the following product decisions:

- Maverick Chat being the only Design Studio composer;
- the native OpenDesign chat being unmounted;
- Maverick owning the normal OpenDesign model execution path;
- custom Maverick UI reproducing OpenDesign project, mode, tools, or settings
  controls;
- treating every native OpenDesign user message as a Maverick runtime turn.

Hosting, workspace isolation, artifact integrity, and app-data rules remain
applicable. Historical implementation details are not active architecture.

## Implementation Mapping (2026-08-28)

The checked-in implementation respects the zero-modification boundary:

- `opendesign_official_release.json` pins and verifies the unchanged official
  OpenDesign OCI release;
- `opendesign_launcher.py` and the Design Studio frontend provide only process,
  isolated-origin, lifecycle, and native-route hosting;
- the Model Access Bridge registers configured API and CLI models through
  supported native agent profiles without Maverick semantic enrichment;
- the external Delegation Bridge uses supported project, conversation,
  message, file, and run APIs and retains only bounded correlation metadata;
- the one-time cutover and official update flow use public-API inventories,
  immutable backups, migration preservation guards, and fail-closed recovery;
  and
- the derived runtime, patch series, web overlay, native-route interception,
  replacement composer, and legacy writer have been removed.

## Decision Summary

There are two separate usage modes.

### Direct OpenDesign mode

The user opens Design Studio and uses OpenDesign directly:

```text
User
  -> native OpenDesign UI and chat
  -> OpenDesign instructions, project context, tools, and execution flow
  -> selected API or CLI model made available by Maverick
  -> native OpenDesign project and artifacts
```

Maverick does not add memories, system prompts, skills, agents, or tools to this
flow. It only makes installed model transports available to OpenDesign.

### Maverick-delegated mode

The user asks a general Maverick agent to perform design work:

```text
User
  -> Maverick Chat and Maverick agent
  -> explicit task brief and selected context
  -> native OpenDesign conversation
  -> OpenDesign instructions, project context, tools, and execution flow
  -> selected API or CLI model made available by Maverick
  -> native OpenDesign project and artifacts
  -> result reference and summary returned to Maverick Chat
```

The additional Maverick information exists only because the Maverick agent
explicitly placed it in that OpenDesign conversation. OpenDesign and its model
do not otherwise gain access to Maverick memory or runtime state.

## Architectural Principles

### 1. OpenDesign remains the complete design product

Maverick must not rebuild OpenDesign features in parallel. OpenDesign owns its
native:

- chat and conversation UI;
- projects and project navigation;
- canvases, sketches, files, and previews;
- Design Systems;
- modes, tools, and design-specific instructions;
- model-facing design workflow;
- history, run state, and results;
- import, export, and other upstream product features.

The Design Studio app remains useful as the Maverick host and integration
boundary, but it should be thin. Its responsibilities are app launch,
authentication, workspace binding, lifecycle, isolation, and the two bridges
defined below. It must not become a second design product.

### 2. OpenDesign specializes the model

A model used from native OpenDesign is specialized by OpenDesign, not by
Maverick. OpenDesign determines the conversation payload, design instructions,
project context, tools, file context, and execution protocol.

Maverick's model inventory answers only a technical question: which model
backends are installed and available to this user and workspace?

### 3. Direct use has no Maverick cognitive context

Direct OpenDesign model calls must not include:

- a Maverick system prompt;
- Maverick Chat history;
- user memories stored by Maverick;
- Maverick agent identity or persona;
- Maverick skills;
- Maverick tools or inter-agent tools;
- hidden planning or orchestration instructions;
- automatic context enrichment;
- hidden model substitution chosen by Maverick.

Authentication, credential delivery, process launch, usage metering, and
stream transport are technical concerns. They do not authorize modification of
the semantic request authored by OpenDesign.

### 4. Delegation is explicit and conversation-scoped

Maverick context enters OpenDesign only when a Maverick agent delegates a task.
The agent selects the relevant information and sends it as part of a visible
message or attachment to a specific OpenDesign conversation.

Delegation must not create a permanent, implicit synchronization between
Maverick memory and OpenDesign. A later direct OpenDesign conversation has no
Maverick context unless the user or another explicit delegation supplies it.

### 5. OpenDesign remains the source of truth

Maverick must not maintain a duplicate writable catalog of OpenDesign projects,
conversations, messages, runs, Design Systems, or files.

The delegation bridge may retain bounded correlation metadata, such as a
workspace id, delegation id, OpenDesign project id, conversation id, run id,
status, and timestamps. That record is transport and audit metadata, not a
second transcript or design database.

### 6. Updates remain upstream and user-controlled

OpenDesign is installed and updated as an upstream product. The user decides
whether and when to update it. Maverick must not require a forked OpenDesign
release or a Maverick rebuild of the OpenDesign UI for each update.

Maverick is responsible for keeping its external bridges compatible, not for
reimplementing or certifying the upstream product before allowing a
user-selected update.

## Target Topology

```text
Maverick Base Shell
  |
  +-- Design Studio host
  |     |
  |     +-- complete native OpenDesign UI
  |     +-- OpenDesign application service and data
  |     +-- Model Access Bridge -------------------+
  |                                                |
  +-- global Maverick Chat                         |
        |                                          |
        +-- Delegation Bridge                      |
              |                                    |
              +-- OpenDesign project/conversation |
                                                   |
Maverick model inventory                           |
  +-- configured API models <----------------------+
  +-- installed CLI models <-----------------------+
```

OpenDesign should run as its own application/service boundary rather than be
merged into the Maverick frontend dependency graph. This preserves upstream
routing, state, dependencies, UI composition, and update behavior.

The surrounding Maverick shell may provide navigation and a workspace launch
surface, but the Design Studio content area presents native OpenDesign. It does
not replace OpenDesign chat, sidebars, tools, settings, or project navigation
with parallel Maverick controls.

## Component Responsibilities

| Component | Authoritative responsibilities |
|---|---|
| OpenDesign | Design UI, chat, projects, conversations, Design Systems, files, tools, runs, results, and design-specific model orchestration. |
| Design Studio host | Launching and embedding OpenDesign, workspace binding, authentication handoff, lifecycle, isolation, and integration health. |
| Model Access Bridge | Discovering and invoking installed API/CLI models without Maverick cognitive enrichment. |
| Maverick Runtime | Normal Maverick agents, global Chat turns, memory access, skills, tools, policy, and agent orchestration outside direct OpenDesign execution. |
| Delegation Bridge | Creating or selecting an OpenDesign project/conversation, submitting an explicit brief, observing progress, cancelling delegated work, and returning result references. |
| Maverick Chat | User-facing generalist interaction, context selection, delegation decisions, progress reporting, and links back to the native OpenDesign conversation. |

The Model Access Bridge and Delegation Bridge are separate contracts. Using a
model from OpenDesign does not imply using a Maverick agent or the Maverick
delegation flow.

## Full Native OpenDesign Installation

Design Studio should install the official upstream OpenDesign distribution
appropriate for the Maverick host platform. The intent is the same product
experience as a normal local OpenDesign installation, not a partial port of its
screens into Maverick.

The installation must preserve:

- the native OpenDesign application structure;
- the native chat and all normal chat actions;
- upstream project and conversation persistence;
- upstream design tools and Design Systems;
- native model selection and model-specific configuration;
- native import/export and artifact behavior;
- upstream data migrations;
- upstream feature evolution.

Integration must use official configuration and supported public provider,
CLI, and application APIs. A content-preserving adapter may exist outside the
OpenDesign process, but the installed OpenDesign package remains unchanged.

If an official release does not expose an interface required by a Maverick
bridge, that bridge is reported as unavailable for that release. Maverick must
not solve the incompatibility with a private patch, injected browser code,
browser automation, direct database access, or a fork. Native OpenDesign must
still start and remain directly usable.

Desktop-only capabilities that require host access must use an explicit
Maverick capability or user grant when running inside a workspace. They should
not be silently removed merely because Design Studio is hosted, and they must
not receive unrestricted access to other workspaces or the whole server by
default.

## Model Access Bridge

### Meaning of a "naked" model

"Naked" means naked relative to Maverick. It does not mean that the foundation
model receives no system instructions at all.

The selected model receives whatever OpenDesign would normally send when used
on a local machine, including OpenDesign's own system instructions, project
context, tools, and conversation. It receives no additional Maverick-authored
cognitive context.

### Model catalog

OpenDesign's native model selector should show the API and CLI models installed
or configured in Maverick for the active user and workspace. Each catalog item
may include technical metadata such as:

- stable model id and display name;
- transport type (`api` or `cli`);
- availability;
- context and media capabilities;
- tool, image, streaming, and cancellation support;
- provider-required configuration state.

Capability metadata informs OpenDesign. Maverick should not silently hide or
replace a selected model merely because another model would be more suitable.
When a model cannot support a requested OpenDesign operation, OpenDesign should
handle or display that limitation in its normal product flow.

### API models

For an API-backed model, the bridge may:

- resolve a scoped credential or provider endpoint;
- translate protocol framing when required;
- forward OpenDesign messages, tools, and media;
- stream provider events back to OpenDesign;
- support cancellation and technical usage accounting;
- normalize transport errors without exposing secrets.

It must not add, remove, summarize, reorder, or semantically rewrite
OpenDesign's model input except where the selected provider protocol itself
requires a lossless representation change.

### CLI models

For an installed CLI model, such as a Codex-style local CLI, OpenDesign should
invoke that CLI through the same kind of local profile or process adapter it
would use outside Maverick.

The bridge may provide an isolated OpenDesign project working directory,
process lifecycle, environment configuration, streaming, and cancellation. It
must not route the request through a Maverick agent session or prepend a
Maverick prompt.

A CLI may have its own native harness, built-in instructions, or process
semantics. Those are part of using that CLI and are not considered Maverick
enrichment. If OpenDesign does not natively support a particular CLI protocol,
the adapter may translate process events, but it must remain content-preserving
and must not turn the CLI into a Maverick agent.

### Allowed and forbidden behavior

| Allowed technical behavior | Forbidden cognitive behavior |
|---|---|
| Model discovery | Maverick memory injection |
| Scoped credential resolution | Maverick system prompt injection |
| Endpoint or process launch | Maverick Chat history injection |
| Protocol framing | Maverick skills or agent persona injection |
| Streaming and cancellation | Hidden planning or delegation |
| Availability and capability metadata | Automatic semantic prompt rewriting |
| Usage and redacted operational audit | Giving OpenDesign the Maverick tool catalog |

The bridge should be described as a **Model Access Bridge**, not as a
"Maverick agent provider". The latter incorrectly suggests that direct
OpenDesign requests run through Maverick's cognitive runtime.

## Direct OpenDesign Mode

The direct-mode sequence is:

1. The user opens Design Studio.
2. Design Studio starts or resumes the workspace's upstream OpenDesign
   installation.
3. The user uses the native OpenDesign project UI and native chat.
4. OpenDesign requests the available model catalog.
5. The user selects a configured API or CLI model.
6. OpenDesign constructs its native model request using its project,
   conversation, tools, and design instructions.
7. The Model Access Bridge executes that request without Maverick context.
8. OpenDesign streams and persists the response using its native behavior.

No Maverick runtime session, Maverick Chat thread, or Maverick memory lookup is
created merely because the user sent a message in OpenDesign.

## Maverick Delegation Bridge

### Purpose

The global Maverick Chat may act as an orchestrator for a design task. It does
not replace the OpenDesign chat and it does not remotely manipulate the
OpenDesign interface through simulated clicks.

It uses an application-level bridge to perform explicit operations such as:

- create or resolve an OpenDesign project;
- create or select a native OpenDesign conversation;
- select a model when the user or task requires one;
- append a user-visible brief and attachments;
- start the native OpenDesign work;
- observe progress and terminal state;
- cancel a delegated operation;
- retrieve artifact references, preview metadata, and a deep link;
- reopen the exact project and conversation in Design Studio.

The bridge must call supported OpenDesign application interfaces and must not
write OpenDesign's database directly.

### Delegation sequence

For a request such as:

> Create a carousel about deforestation using what you know about me from
> memory.

the sequence is:

1. The user sends the request to Maverick Chat.
2. The Maverick agent decides that OpenDesign is the appropriate specialized
   application.
3. The agent retrieves only the memories and other sources it is authorized to
   use and considers relevant to the task.
4. The agent prepares a bounded brief containing the design request, selected
   context, desired output, constraints, and approved assets.
5. The Delegation Bridge creates or selects the appropriate OpenDesign project
   and conversation.
6. The bridge inserts the brief and attachments into that native conversation,
   visibly attributed as delegated by Maverick.
7. OpenDesign performs the task using its native chat, design workflow, tools,
   and selected naked model.
8. The bridge observes progress without becoming the model execution loop.
9. OpenDesign persists the conversation, files, and results as their source of
   truth.
10. Maverick receives a bounded result summary, identifiers, artifact
    references, and a deep link to the exact OpenDesign state.
11. The user may continue the work directly in native OpenDesign.

### Delegation context

The semantic delegation payload should be representable as a visible message
and attachments. It may contain:

- the user's instruction;
- a task objective and expected deliverables;
- selected memory facts or summaries;
- source provenance appropriate for user inspection;
- brand, audience, tone, and format constraints;
- approved project and Design System references;
- files, images, or other authorized assets;
- completion criteria.

Transport-only metadata, such as `delegation_id`, workspace binding, and
correlation ids, may remain outside the model-visible message.

The payload must not implicitly expose all Maverick memory, all Chat history,
other workspaces, or unrestricted Maverick tools. The agent decides what to
send, and that decision is the only source of Maverick semantic context inside
the delegated OpenDesign conversation.

### Attribution and continuity

Delegated content should be identifiable in the OpenDesign conversation, for
example with a display-safe label such as:

```text
Brief delegated by Maverick
```

The native conversation must remain usable after Maverick disconnects. If the
user opens Design Studio, the complete delegated turn, model response, project
changes, and subsequent direct messages should be present in the normal
OpenDesign history.

Maverick should return a deep link to this state rather than copying the whole
OpenDesign transcript into its own storage.

### Preventing recursive delegation

In this architecture, a model called by OpenDesign does not receive the
Maverick tool catalog or a tool that delegates back to Maverick. Therefore a
normal direct or delegated OpenDesign run cannot recursively create another
Maverick-to-OpenDesign delegation.

The Delegation Bridge is an authenticated capability of the outer Maverick
agent, not a tool automatically exposed to the inner OpenDesign model. If a
future product decision introduces bidirectional delegation, it must add
explicit origin and depth controls at that time.

## State and Data Ownership

### OpenDesign-owned state

OpenDesign is authoritative for:

- projects;
- conversations and messages;
- chat history;
- runs and native run state;
- Design Systems;
- canvases, sketches, project files, and generated artifacts;
- model selection stored by OpenDesign;
- native settings and upstream migrations.

### Maverick-owned state

Maverick is authoritative for:

- users, authentication, and workspace membership;
- global Maverick Chat and agent sessions;
- Maverick memories and their access policy;
- installed/configured model inventory;
- API credentials and CLI availability;
- app installation, lifecycle, and workspace binding;
- delegation authorization and bounded correlation metadata;
- platform-level usage, health, and redacted audit data.

### State that must not be duplicated

Maverick must not create a parallel writable copy of:

- the OpenDesign project catalog;
- the OpenDesign conversation transcript;
- Design Systems;
- OpenDesign run state;
- project file contents merely for synchronization.

Maverick may cache display-safe summaries or references for the global Chat,
but OpenDesign identifiers and APIs remain canonical.

## Workspace and Security Boundary

Installing OpenDesign as a complete product does not remove Maverick workspace
isolation.

Each Design Studio binding must resolve to the correct workspace-scoped
OpenDesign data and authorized project roots. A model or delegated task in one
workspace must not read projects, memories, credentials, or assets from another
workspace.

The model bridge should prefer scoped credential handles or controlled process
launch over exposing raw provider secrets to the browser. This is a transport
security rule and does not authorize Maverick to modify the model's semantic
input.

Assets supplied by a Maverick agent must enter OpenDesign through supported
OpenDesign import or project-file interfaces. Host paths and unrelated
workspace storage must not be injected into the OpenDesign data store.

When an upstream feature needs broader local-machine access, Maverick should
request an explicit user capability for the active workspace. The goal is
native feature availability with visible authority, not silent removal of the
feature or silent server-wide access.

## Update Model

### User-controlled updates

The user chooses whether and when to install an OpenDesign update, as with a
normal local installation. Maverick should expose upstream version and update
information without converting every update into a custom Maverick
development release.

The normal update path is:

1. the user accepts an official upstream update;
2. the upstream application/runtime and its migrations are installed using the
   supported OpenDesign mechanism;
3. OpenDesign restarts on the updated version;
4. the external Maverick bridges perform a lightweight capability handshake;
5. native OpenDesign remains available even if one optional Maverick bridge
   needs an adapter update.

Maverick may record the installed version, preserve operational diagnostics,
and keep a recoverable prior package or data backup where practical. These are
safety mechanisms, not a requirement to fork, rebuild, or pre-certify
OpenDesign before honoring the user's update decision.

### Compatibility strategy

The most durable integration uses stable, upstream-supported protocols:

- a standard model/provider protocol for the Model Access Bridge;
- a supported application or conversation API for the Delegation Bridge;
- capability negotiation rather than assumptions tied to private UI details.

An upstream OpenDesign release is responsible for the upstream product. The
Maverick project is responsible only for its two external bridge contracts.

If a bridge is temporarily incompatible after an update:

- OpenDesign should still start and remain directly usable;
- the affected integration should report a clear bounded error;
- existing OpenDesign projects and conversations must remain intact;
- Maverick must not fall back to hidden UI automation or duplicate state;
- updating the bridge must not require replacing native OpenDesign UI.

## Failure and Recovery Behavior

### Model bridge unavailable

OpenDesign remains the project and conversation owner. It reports the selected
model as unavailable using its normal model configuration experience. Maverick
must not silently execute the request through a different agent.

### Delegation bridge unavailable

Direct OpenDesign use remains available. Maverick Chat reports that delegation
could not be started and does not fabricate an OpenDesign result.

### Maverick disconnects during delegated work

Once OpenDesign accepts the native conversation turn, its run may continue
independently. Maverick may reconnect using correlation metadata and query the
canonical OpenDesign state.

### Duplicate delegation submission

The bridge must use an idempotent delegation identifier so a retry cannot
append the same brief or start the same work twice.

### Update incompatibility

A bridge compatibility problem must degrade only that bridge. It must not
corrupt OpenDesign data or make native OpenDesign dependent on a custom
Maverick OpenDesign build.

## Implemented Rollout

The implementation uses no custom OpenDesign build. It removed the former
customization and connects two external bridges to an official, unchanged
OpenDesign installation.

### What happens to the current `app_id: design-studio`

The `design-studio` app identity remains so existing Maverick navigation,
workspace binding, authorization, and data location do not need a second app or
a parallel migration target. Its current implementation is replaced in place;
it is not retained as an alternative mode.

| Keep | Remove |
|---|---|
| `app_id: design-studio` and its shell registration | The Maverick-derived OpenDesign package, patch series, and web overlay |
| Canonical OpenDesign workspace data | Native-chat suppression and duplicate project/settings/tools UI |
| Thin launch, authentication, isolation, lifecycle, and data-volume mechanics | `/api/runs` interception and normal-turn Maverick runtime execution |
| Official artifact verification | Writable Maverick OpenDesign app-config and conversation/runtime bindings |
| Explicit Storage references where still useful | The Design Studio replacement composer and special runtime controls in global Chat |

The first cutover should replace the customized installation with the
**unchanged official release matching the currently pinned OpenDesign version**.
For the audited implementation, that means official OpenDesign `0.16.1` first.
Do not combine this replacement with an OpenDesign version upgrade. Keeping the
version constant isolates hosting and integration changes from upstream data
schema changes.

The in-place replacement sequence is:

1. run the official same-version package against a copy of the workspace data;
2. verify the canonical OpenDesign projects, conversations, messages, Design
   Systems, files, artifacts, settings, and runs;
3. stop legacy Chat/runtime writers and create the final backup;
4. point the existing `design-studio` launch and data binding to the official
   package and enable native OpenDesign as the only writer; and
5. after the verification/recovery window, delete the legacy implementation
   listed in the Remove column.

The old implementation and the new installation may coexist only in isolated
development or restored test workspaces. They must never both write the same
real workspace. Official version updates begin only after this same-version
replacement has passed.

The work was completed in the following order. Step 1 was deliberately a
bounded vertical slice completed in a disposable workspace before any real
data or legacy writer changed.

### Step 1: run official OpenDesign unchanged

- Use the official Linux package or OCI image already referenced by Design
  Studio.
- Do not apply the current runtime, web-build, or React patches.
- Do not build or overlay OpenDesign web assets.
- Start it with a disposable workspace-scoped data directory.
- Open the native root/Home route and verify native chat, projects,
  conversations, tools, Design Systems, settings, history, import, and export.
- Repeat the proof with both Maverick bridges disabled.

**Done when:** the running package digest matches the official artifact, the
complete native UI is visible, and OpenDesign works directly without Maverick
Chat or a Maverick runtime session.

### Step 2: make Design Studio a thin host

Keep only these host responsibilities:

- official package selection and process start/stop;
- workspace-scoped persistent OpenDesign data;
- outer Maverick authentication and isolated browser origin;
- lifecycle/readiness reporting; and
- native OpenDesign deep-link launch.

All OpenDesign application traffic, including native chat, runs, model
selection, projects, conversations, settings, and updates, goes to OpenDesign.
Maverick must not intercept those operations or rewrite their requests or
responses.

Remove the alternative Maverick project catalog, create-project controls,
native-chat suppression, settings/tools commands, and injected UI behavior.
Host authentication and lifecycle UI may surround OpenDesign but must not be
inserted into its application.

**Done when:** a browser/network trace shows the official OpenDesign UI talking
to its own native endpoints, with no Maverick handler replacing a normal
OpenDesign operation.

### Step 3: expose Maverick models as naked transports

Connect the Model Access Bridge through standard provider endpoints and native
CLI profiles supported by OpenDesign.

For API models, Maverick may resolve credentials, forward the exact
OpenDesign-authored semantic request, stream the provider response, cancel it,
and return technical errors.

For CLI models such as Codex, Maverick may make the configured executable and
its technical environment available to OpenDesign and supervise the process.
OpenDesign supplies the prompt, conversation, project directory, tools, files,
and Design System through its normal native adapter.

Neither path may create a Maverick runtime session or add Maverick system
prompts, memory, Chat history, personas, skills, tools, planning, or hidden
model substitution. The model remains specialized by OpenDesign and naked only
relative to Maverick.

**Done when:** at least one API model and one CLI model appear in the native
OpenDesign selector and pass streaming, cancellation, and semantic-transparency
tests without creating Maverick agent/runtime state.

### Step 4: add external delegation from Maverick Chat

Implement the Delegation Bridge as an external client of supported public
OpenDesign APIs. It performs only this flow:

1. receive an explicit brief and authorized attachments from a Maverick agent;
2. select or create the native OpenDesign project;
3. select or create the native OpenDesign conversation;
4. append one ordinary visible message stating that it was delegated by
   Maverick;
5. start the normal native OpenDesign run;
6. observe status, progress, cancellation, and result references; and
7. return preview metadata and a deep link to that exact native conversation.

The Maverick agent, not the bridge, decides which authorized memory is relevant
and writes it into the brief. The bridge does not have general access to
Maverick memory and does not enrich the message silently.

Maverick stores only delegation id, status, canonical OpenDesign ids, event
cursor, result references, and deep link. It does not copy the OpenDesign
transcript, project, Design System, files, artifact bodies, or model request.
Retries use an idempotency key so they cannot append the brief or start the run
twice.

If the installed official OpenDesign release does not provide a required public
API, delegation is shown as unavailable for that release. Maverick must not use
a patch, injected script, browser automation, or direct database access as a
fallback.

**Done when:** an agent can delegate once, cancel or follow the native run,
open the returned deep link, and continue in the same native OpenDesign
conversation. The delegated visible brief must be the only Maverick cognitive
content present there.

### Step 5: cut over existing data once

- Back up the canonical OpenDesign data directory and the legacy Maverick
  correlation/config files.
- Restore the backup into a disposable workspace and run only official
  OpenDesign migrations.
- Compare projects, conversations, ordered messages, Design Systems, files,
  artifacts, settings, and run references through supported APIs.
- Stop all legacy `chat.submit_turn` and Maverick runtime-bridge writers before
  enabling the native writer for a real workspace.
- Keep existing Maverick runtime threads only as read-only historical Chat
  records; do not import or merge them into OpenDesign.
- Stop writing the Maverick OpenDesign app-config projection and old
  conversation/runtime bindings.

The old and new paths must never write concurrently. Before the first native
write against migrated data, rollback may restore the full backup. After that
point, the old runtime writer is not a valid fallback; OpenDesign remains the
writer even when either optional bridge is disabled.

**Done when:** the before/after canonical inventory matches, legacy state is
read-only, and exactly one writer—native OpenDesign—is active.

### Step 6: enable official updates and remove the legacy integration

The user selects an official OpenDesign update. Maverick verifies and installs
that official package, backs up the data, runs the supported upstream
migration, restarts OpenDesign, and checks the two external bridge contracts.
A bridge incompatibility disables only that bridge; it must not prevent native
OpenDesign from starting.

After the cutover is verified, remove:

- the OpenDesign patch series, custom web overlay, and derived build path;
- `/api/runs` interception, Maverick runtime system prompts, terminal callbacks,
  and `runtime_bridge.py` normal-turn state;
- the writable OpenDesign app-config projection;
- the Design Studio-specific replacement composer and controls in global Chat;
- duplicate project/sidebar widgets and OpenDesign settings/tools UI commands;
  and
- permissions used only to create Maverick runtime sessions for normal
  OpenDesign turns.

Keep only the official package host, persistent workspace data, Model Access
Bridge, Delegation Bridge, and explicit Storage/reference operations.
Mark `docs/architecture/design_studio_runtime_bridge.md` as historical after the
last legacy writer is removed.

**Done when:** the user can update to another official release without a
Maverick OpenDesign rebuild, direct native use remains available with both
bridges disabled, and no active code path modifies or replaces OpenDesign.

## Acceptance Criteria

The target architecture is complete only when all of the following are true.

### Native product

- `app_id: design-studio` launches a verified official OpenDesign artifact
  without patches, overlays, or injected code.
- Design Studio presents the complete native OpenDesign UI and chat.
- Projects, conversations, tools, Design Systems, history, and settings are
  OpenDesign-native.
- No Maverick component reproduces those controls as an alternative source of
  truth.
- No legacy Design Studio runtime writer remains active after cutover.

### Naked models

- The OpenDesign model selector lists authorized installed API and CLI models.
- Direct model requests contain only OpenDesign-authored semantic context.
- No Maverick memory, agent prompt, Chat history, skills, or tool catalog is
  injected.
- API and CLI transports support their declared streaming, cancellation,
  media, and tool capabilities.
- Maverick does not silently substitute a different model.

### Delegation

- Maverick Chat can create or select an OpenDesign project and conversation.
- Delegated context is bounded, explicit, and visible in that conversation.
- The selected OpenDesign model remains naked relative to Maverick and receives
  Maverick information only through the delegated brief.
- Maverick can observe status, cancel, retrieve result references, and return a
  deep link.
- The user can continue the same conversation directly in OpenDesign.
- Retrying a delegation does not duplicate the message or run.

### Ownership and isolation

- OpenDesign remains canonical for design state and artifacts.
- Maverick stores only bounded delegation correlation and display-safe result
  references.
- Cross-workspace project, memory, asset, and credential access is denied.
- Provider secrets are not exposed to the browser or persisted in design
  conversations.

### Updates

- The user can choose an official OpenDesign update without waiting for a
  Maverick UI fork to be rebuilt.
- OpenDesign data follows supported upstream migration behavior.
- Bridge capability is checked after the update.
- A bridge problem does not prevent native OpenDesign from starting or damage
  its data.

## Focused Verification Strategy

Implementation verification should remain bounded and should not require the
entire Maverick suite for routine work.

The minimum focused proofs are:

1. **Semantic transparency:** compare the OpenDesign-authored request at the
   model boundary with the bridged request and prove no Maverick cognitive
   fields were added.
2. **Direct/delegated separation:** prove that direct mode has no memory
   context, while delegated mode contains only the explicit brief.
3. **API and CLI fidelity:** run one representative model of each transport and
   verify streaming, cancellation, and supported tools/media.
4. **Native continuity:** complete a delegated turn, reopen it directly in
   OpenDesign, and continue the same conversation.
5. **Workspace isolation:** attempt cross-workspace project, asset, model, and
   delegation access and prove denial.
6. **Update compatibility:** update a disposable OpenDesign installation,
   confirm native startup, and run the bridge capability handshake.
7. **Graceful degradation:** disable each bridge independently and prove native
   OpenDesign data remains intact and directly accessible.

Full release testing remains appropriate for changes to installation,
migration, isolation, credential delivery, or data recovery. Chat-side bridge
presentation changes should use the smallest affected Chat and Design Studio
tests.

## Alternatives Rejected

### Replace native OpenDesign chat with Maverick Chat

Rejected because it removes a strong upstream experience, duplicates product
features, increases UI coupling, and makes upstream updates expensive.

### Run every OpenDesign turn as a Maverick agent turn

Rejected because direct OpenDesign use must not inherit Maverick memories,
prompts, tools, or agent semantics. Model access and Maverick agent execution
are different concerns.

### Import OpenDesign source directly into Maverick's frontend

Rejected because it couples dependency graphs, routing, CSS, build systems,
and release cycles. OpenDesign should remain a complete application boundary.

### Control OpenDesign through browser automation

Rejected because simulated clicks are fragile, difficult to recover, and tied
to private UI details. Delegation must use an application-level API.

### Maintain duplicate Maverick and OpenDesign design state

Rejected because two writable project or conversation catalogs inevitably
drift. OpenDesign is the sole design-domain source of truth.

### Automatically inject Maverick memory into all OpenDesign chats

Rejected because native OpenDesign use must remain equivalent to a normal
local installation. Memory enters only through an explicit Maverick
delegation.

## Final Product Contract

The product contract can be summarized in three sentences:

1. **OpenDesign inside Design Studio is the complete native OpenDesign product.**
2. **Models installed in Maverick are exposed to OpenDesign as naked technical
   model transports, not as Maverick agents.**
3. **Maverick influences an OpenDesign conversation only when a Maverick agent
   explicitly delegates a task and inserts selected context into that specific
   conversation.**
