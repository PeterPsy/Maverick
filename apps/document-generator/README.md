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
./scripts/maverick app validate document-generator --workspace default
./scripts/maverick app register-local document-generator --workspace default
./scripts/maverick app install-local document-generator --workspace default
./scripts/maverick app status document-generator --workspace default
./scripts/maverick app package document-generator --workspace default
```
