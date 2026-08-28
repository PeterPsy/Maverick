---
name: design-studio-ops
description: Delegate an explicit design brief to the native OpenDesign chat, follow or cancel its native run, and open the exact conversation.
---

# Design Studio Ops

Design Studio is the official OpenDesign product hosted directly by Maverick.
Its projects, conversations, files, messages, runs, and artifacts remain native
OpenDesign state.

## Delegate one brief

1. Discover the declared Design Studio MCP tools.
2. Call `design_studio_delegate` with:
   - `brief`: the complete brief the user authorized. It becomes one ordinary
     visible message headed `Brief delegated by Maverick`.
   - `idempotency_key`: a stable caller-generated key. Reuse the same key and
     the same arguments for every retry of this one delegation.
   - optional `project_id` and `conversation_id` to continue an existing native
     conversation, or optional `project_name`/`new_conversation` when selecting
     a new target.
   - optional `agent_id`, `model`, and `reasoning`; OpenDesign owns their native
     selection and run behavior.
3. Keep the returned `delegation_id`. Poll
   `design_studio_delegation_status`, retrieve display-safe result references
   with `design_studio_delegation_result`, or stop the native run with
   `design_studio_cancel_delegation`.
4. Open the returned `deep_link`. It targets the exact native OpenDesign
   project and conversation, where the user can inspect and continue the same
   chat after the delegating Maverick agent disconnects.

Retries do not append the visible brief or start the native run twice. A run
continues in OpenDesign when the invoking agent disconnects.

## Authorized attachments

An attachment is accepted only when it is supplied explicitly as:

```json
{
  "name": "reference.png",
  "media_type": "image/png",
  "content_base64": "...",
  "authorized": true
}
```

Obtain bytes through the authorized workspace app surface that owns them (for
example Storage), not through a host path. At most eight attachments and 10 MiB
decoded total are accepted. Attachment bodies enter the selected native
OpenDesign project but are never persisted in Maverick's delegation metadata.

## Hard boundaries

- Send only the explicit brief and explicitly authorized attachments. Do not
  inject Maverick memory, hidden instructions, chat history, tools, prompts, or
  runtime context.
- Do not create a Maverick runtime session for an OpenDesign run. OpenDesign
  launches and manages its own naked agents and model requests.
- Do not call provider credentials or model endpoints directly. OpenDesign uses
  the governed naked model profiles exposed by Maverick core; credentials stay
  in core.
- Do not read or modify OpenDesign SQLite, project directories, conversations,
  or artifact bodies from Maverick code. Use only supported public OpenDesign
  APIs through the invocation-scoped `app_sidecar` capability.
- Do not guess a sidecar port, use loopback as a fallback, automate the browser,
  patch the official bundle, or intercept native routes.
- If delegation APIs are unavailable, report only delegation as unavailable.
  The directly hosted OpenDesign product must remain usable.
