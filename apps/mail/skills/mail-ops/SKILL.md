---
name: mail-ops
description: Use Maverick Mail safely through its app-owned CLI, MCP, and reference surfaces.
---

# Mail Ops

Use Mail through its official Maverick surfaces. Do not read `data/mail/mail.sqlite` directly and do not copy whole email threads into Chat unless the user explicitly asks for full content.

Preferred workflow:

- Search first with `mail_list_threads` or `mail_search_messages`.
- Read a bounded thread with `mail_get_thread` and set `max_body_chars` to the smallest useful value.
- Cite `email_thread` or `email_message` reference ids when sharing context with Chat, CRM, Memory, Docs, or Checklist.
- Create drafts with `mail_create_draft` or `mail_update_draft` before sending.
- Treat `mail_send`, `mail_send_draft`, and approved-send tools as high-impact actions. Use dry-run first, show recipients, subject, full body, thread context, and attachment filenames, then require explicit user confirmation before sending.
- Prefer `mail_send_approved` or `mail_send_draft_approved` after the user confirms a dry-run preview. These actions consume the latest server-side preview for the draft and do not require the model or shell to handle `confirmation_token`.
- Use `confirm=true` with `confirmation_token` only as a fallback. If the CLI output profile redacts the token as `<redacted>`, rerun the preview with `MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE=full` only if absolutely necessary, keep the token in memory, and never print or store it.
- Save attachments to Storage only when requested or operationally useful. When using `mail_save_attachments`, inspect `attachment_summary` and `document_part_hints` before deciding whether more source material is missing.

Security rules:

- Never ask the user to paste OAuth refresh tokens into chat.
- Never return provider tokens, authorization headers, raw cookies, or secret identifiers in user-visible text.
- Summarize mail content narrowly and preserve the original Mail reference link.
- Use app-to-app references for CRM/Memory links instead of ad hoc notes.
