# Document Generator

Agent-facing document generation and document text extraction app for DOCX, PPTX, PDF, and XLSX files.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract declares the bundled `document-generator-docs` skill and the `document` reference entity.
- App-owned storage lives under `data/document-generator/` for state, templates, and generation jobs.
- Persisted `view_surfaces` cover generated document job filters and curated generated-document selections.
- The `document-generator` CLI action `extract_text` and MCP tool `document_generator_extract_text` read workspace files under `storage/generated/` or `storage/uploaded/` and return extracted text for `pdf`, `docx`, `pptx`, and `xlsx`.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id document-generator --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id document-generator --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id document-generator --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id document-generator --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id document-generator --workspace default --json
```
