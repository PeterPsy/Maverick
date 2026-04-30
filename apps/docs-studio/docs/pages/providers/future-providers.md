# Claude Code, Gemini CLI, OSS, and API-key models

Maverick should be able to support multiple provider families without changing app contracts or workspace data layout.

## Runtime-style examples

| Provider | Expected shape |
| --- | --- |
| Claude Code | local CLI/process adapter with provider-specific session handling |
| Gemini CLI | local CLI/process adapter with streaming and tool-event translation |
| Kimi or other coding CLIs | runtime-style backend with model capability metadata |
| Local OSS runtime | local server or process adapter, possibly OpenAI-compatible |

## Hosted API-style examples

| Provider | Expected shape |
| --- | --- |
| OpenAI-compatible API | API key binding, model catalog, streaming response adapter |
| Anthropic-compatible API | API key binding, model metadata, tool/event normalization |
| Self-hosted gateway | URL plus secret binding, workspace selection, capability declaration |

## Implementation principle

Adding a provider should add a provider adapter and metadata. It should not require changing app storage, chat project records, or app contracts.
