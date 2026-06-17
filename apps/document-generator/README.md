# Document Generator

Agent-facing document generation, document text extraction, and Docling-backed Markdown conversion app for DOCX, PPTX, PDF, and XLSX files.

## Contract Notes

- Backend, CLI, MCP, and supporting frontend entrypoints are declared in `app_contract.json`; the frontend is marked `presentation.frontend_role: supporting` because document generation and conversion are primarily used through tools and app-owned data surfaces.
- The contract declares the bundled `document-generator-docs` skill and the `document` reference entity.
- App-owned storage lives under `data/<local_app_id>/` for state, templates, and generation jobs; the builtin install uses `data/document-generator/`.
- Persisted `view_surfaces` cover generated document job filters and curated generated-document selections.
- The `document-generator` CLI action `extract_text` and MCP tool `document_generator_extract_text` read workspace files under `storage/generated/` or `storage/uploaded/` and return extracted text plus extraction metadata for `pdf`, `docx`, `pptx`, and `xlsx`.
- The `document-generator` CLI action `patch_pdf_text` and MCP tool `document_generator_patch_pdf_text` replace matched text in workspace PDFs, save generated outputs under `storage/generated/document-generator/pdf-edits/<job_id>/`, and return hash, match counts, and a visual crop artifact when available.
- The `document-generator` CLI action `modify_uploaded_document` and MCP tool `document_generator_modify_uploaded_document` provide a task-level helper for simple uploaded-PDF date replacements, returning candidate dates when confirmation is required.
- The `document-generator` CLI action `convert_to_markdown` and MCP tool `document_generator_convert_to_markdown` use Docling to convert workspace files up to 10 MiB under `storage/generated/` or `storage/uploaded/` into Markdown artifacts under `storage/generated/document-generator/markdown/<job_id>/`.
- PyMuPDF is a Maverick runtime dependency used by `patch_pdf_text`. Docling is loaded lazily for Markdown conversion; install the extra with `python3 -m pip install -e '.[document-generator]'` before using `convert_to_markdown`.
- App-owned CLI/MCP descriptor sidecars live under `cli/command_schemas.json` and `mcp/tool_schemas.json` so agents can discover conversion arguments and result shapes through scoped inspect calls.

## SDK Flow

From the repository root, validate this installation-level app source directly:

```bash
./scripts/maverick core cli run core.app-sdk.validate --arguments-json '{"app_root":"apps/document-generator"}' --json
```

Workspace-local registration and install commands apply to app projects under `workspaces/<workspace_id>/apps/`, not this built-in installation-level source tree.
