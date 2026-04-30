# Provider architecture

The runtime layer is provider-backed, but providers are not the runtime itself.

## Ownership split

| Layer | Owns |
| --- | --- |
| Runtime | sessions, turns, events, execution policy, workspace context |
| Provider adapter | process launch, session/thread linking, protocol translation |
| Provider registry | provider definitions, capabilities, model metadata |
| Secrets | credential values and controlled resolution |

## Provider kinds

| Kind | Examples | Notes |
| --- | --- | --- |
| Runtime-style backend | Codex, Claude Code, Gemini CLI, Kimi, local OSS runtime | often runs as a process with session state |
| Hosted API-style provider | OpenAI-compatible API, Anthropic API, local model gateway | uses API keys and request/response or streaming APIs |

## Core rule

Provider definitions, credential bindings, capability metadata, and workspace selection are separate records. Raw secret values never belong in ordinary provider or runtime records.
