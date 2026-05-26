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
- Treat `mail_send` and `mail_send_draft` as high-impact actions. Use dry-run first and require explicit user confirmation before passing `confirm=true`.
- Save attachments to Storage only when requested or operationally useful.

Security rules:

- Never ask the user to paste OAuth refresh tokens into chat.
- Never return provider tokens, authorization headers, raw cookies, or secret identifiers in user-visible text.
- Summarize mail content narrowly and preserve the original Mail reference link.
- Use app-to-app references for CRM/Memory links instead of ad hoc notes.
