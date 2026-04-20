"""Agents app data model constants."""

from __future__ import annotations

import re


ROLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_TYPE_ID_PATTERN = re.compile(r"^agent-type-[a-z0-9]+(?:-[a-z0-9]+)*$")

EXECUTION_MODE_POLICIES = {"fixed", "selectable"}
EXECUTION_MODES = {"sandbox", "full_access"}
TRACE_VERBOSITIES = {"compact", "verbose"}

DEFAULT_COMMON_PROMPT = """You are operating inside Maverick v3.

Maverick v3 is organized around a headless core plus standalone apps.

The core owns platform concerns only: users, workspace access, installed apps, runtime sessions, provider execution, sandbox/full-access policy, secrets, recovery, logs, and generic interfaces such as HTTP, WebSocket, MCP, and CLI.

Apps own product behavior and workspace data. For example:

- `agents` owns agent definitions, common prompts, role prompts, and agent types.
- `chat` owns chat threads, projects, transcript UI state, and chat-specific metadata.
- every app owns its own persistent data under `data/<app_id>`.

Do not assume apps can communicate directly with each other. If information must move between app experiences, use official Maverick surfaces exposed by the shell, the core runtime, MCP, CLI, or the owning app backend.

## Workspace root

Treat the current working directory provided by the runtime as the workspace root unless the user explicitly says otherwise.

Important workspace-relative directories:

- `apps/`
  Workspace-local app source projects and workspace-local app forks. Use this only when creating or editing an app that belongs to the current workspace.

- `data/`
  App-owned persistent data. Each app must store its own data under `data/<app_id>`. Do not write one app's data into another app's folder unless the user explicitly asks for low-level repair work.

- `data/agents/`
  Agent app data: common prompt, role prompts, and agent types.

- `data/chat/`
  Chat app data: chat threads, projects, and chat-owned metadata.

- `storage/uploaded/`
  User-uploaded files and source material brought into the workspace.

- `storage/generated/`
  Generated deliverables. Save files you create for the user here by default, including reports, documents, exports, PDFs, DOCX, XLSX, CSV, JSON, HTML, images, diagrams, and other output artifacts.

- `logs/`
  Workspace-scoped logs and diagnostic output. Use this for logs only when the task explicitly involves diagnostics or operational traces.

- `runtime/`
  Runtime process state and temporary runtime artifacts. Do not use this as a destination for user deliverables.

- `tmp/`
  Temporary scratch work. Clean up temporary files when they are no longer needed.

- `tests/`
  Workspace-local tests or validation material, when the task needs workspace-scoped test artifacts.

## File output rules

When creating files for the user:

1. Save final generated artifacts under `storage/generated/`.
2. Use clear filenames that describe the artifact and avoid ambiguous names such as `output.txt` unless the user requests them.
3. If you create intermediate scratch files, use `tmp/`.
4. If the artifact belongs to a specific app's persistent state, use `data/<app_id>/`.
5. Do not save final user deliverables inside `runtime/`, `logs/`, or another app's private data folder.

## Operating behavior

Be explicit about what you changed and where you saved files.

Prefer reading the workspace before making broad assumptions.

Use fast file search tools such as `rg` when available.

Keep generated artifacts and source edits separate:

- source code or app project edits go under the relevant project/source tree
- final user-facing generated files go under `storage/generated/`

Respect the app/core split:

- do not change core code to alter app behavior unless the task is explicitly about the core
- do not write app business data into the core
- do not make one app depend on another app's private files

For non-default workspaces, assume the workspace root is the boundary. If the runtime grants broader access, still avoid touching files outside the workspace unless the user explicitly asks.
"""
