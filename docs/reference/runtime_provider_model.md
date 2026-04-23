# Runtime Provider Model

## Overview

The runtime layer is provider-backed.

Maverick owns:

- runtime session lifecycle
- turn lifecycle
- execution policy
- workspace context
- streaming and persistence of runtime events

The provider adapter owns:

- provider process launch
- provider session or thread linking
- provider-specific protocol translation

## Current Provider Reality

The current practical backend is Codex.

Important implications:

- local evaluation expects the Codex CLI to be available when testing Codex-backed runtime paths
- non-default workspaces are intended to remain sandbox-first
- provider adapters may need helper binaries such as `rg`
- network access for providers is not equivalent to unconstrained filesystem access

## What External Reviewers Should Know

- provider abstraction is a real architectural boundary, not only an internal naming trick
- Codex app-server is the current implementation choice, not the permanent platform identity
- setup docs must separate "Maverick runs" from "Codex-backed agents run"

## Local Evaluation Guidance

Use the local host and core verification even without provider setup when evaluating:

- architecture
- built-in app hosting
- workspace layout
- app contracts
- CLI and MCP discovery

Provider setup is required only for end-to-end agent execution paths that depend on Codex.
