---
name: generate-image
description: Create an image with the image generation tool, save it into the active workspace with a suitable filename, and verify it through Storage.
---

Use this skill when the user asks to create an image and wants the result saved in the current Maverick workspace.

Workflow:

1. Generate the image with the `image_gen` tool.
2. Treat the generated image in the current runtime session as the source artifact. Leave the original generated file in place unless the user explicitly asks to delete it.
3. Copy the image into the active workspace under `storage/generated/`.
4. Choose a concise descriptive filename based on the request content.
5. Sanitize the filename to lowercase kebab-case and keep an appropriate image extension such as `.png`.
6. If a filename collision exists, append a short differentiator instead of overwriting silently.
7. Verify the saved workspace artifact through official Storage app surfaces when inspection or confirmation is needed.
8. Report the final workspace path back to the user.

Rules:

- Save final user-facing image artifacts under `storage/generated/`, not under `runtime/`.
- Do not claim the image is saved until the copied file exists in the workspace.
- Prefer Storage app CLI or MCP surfaces for inspection, metadata lookup, rename, or confirmation of generated files.
- Do not move or delete the original runtime-generated image unless the user explicitly requests cleanup.
- If the user specifies a filename, use it after sanitizing it for workspace storage.
