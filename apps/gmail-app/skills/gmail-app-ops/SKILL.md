---
name: gmail-app-ops
description: Use Gmail App to search Gmail threads, summarize relationship context, expose Gmail references, and send email only after explicit confirmation.
---

# Gmail App Operations

Use this skill when the user asks you to work with their Google Workspace Gmail account through Maverick.

## Required Boundaries

- Use Gmail App MCP, CLI, or backend surfaces.
- Do not read or write another app's private files.
- Do not save directly into CRM, Memory, or any other app. Expose Gmail references and let the consuming app or agent use official generic surfaces.
- Do not send email unless Gmail App has an explicit approval for that exact message.
- Do not bulk send.
- Do not store Gmail OAuth tokens in files or chat messages.

## Typical Flow

1. Check connection with `gmail_app_connection_status`.
2. Search requested threads with `gmail_app_search_threads`.
3. Read selected thread details with `gmail_app_get_thread`.
4. Summarize selected threads with `gmail_app_summarize_thread`.
5. Ask the user which suggestions to save.
6. Resolve or summarize durable Gmail references with `gmail_app_reference_resolve` or `gmail_app_reference_summarize`.
7. Prepare replies with `gmail_app_prepare_reply`.
8. Request explicit approval with `gmail_app_request_send_approval`.
9. Send only with `gmail_app_send_approved` after the user confirms.

## Confirmation Standard

Before sending, show:

- recipients
- subject
- full body
- thread context, if any

The user's confirmation must clearly authorize sending that message.
