---
name: document-generator-docs
description: "Use the Document Generator app CLI or MCP tool first for workspace document operations: create DOCX, PPTX, PDF, and XLSX files, edit PDFs, transform XLSX/CSV/TSV spreadsheets, extract text, or convert documents to Markdown."
---

# Document Generator Docs

Use this skill when a user asks an agent to create, edit, transform, inspect, read, extract from, or convert a workspace document or spreadsheet.

## Default Document Path

For files under `storage/uploaded/` or `storage/generated/`, use Document Generator before checking for or installing ad hoc packages such as `openpyxl`, `xlsxwriter`, `pandas`, `xlsx`, `xlsx2csv`, LibreOffice, or `soffice`.

Fallback to direct libraries or temporary virtualenvs only when the official Document Generator CLI/MCP surface cannot express the requested operation, or when the Document Generator call fails with a concrete unsupported-operation error. If you fallback, state which Document Generator action was tried or why it does not apply.

## App Scripts

The app exposes one official CLI command plus MCP tools for generation, PDF text patching, spreadsheet transforms, extraction, Markdown conversion, references, and view state. Use those surfaces for real work.

Implementation scripts behind those surfaces:

- CLI entrypoint: `<repo>/apps/document-generator/cli/app_cli.py`
- MCP entrypoint: `<repo>/apps/document-generator/mcp/server.py`
- shared service: `<repo>/apps/document-generator/backend/service.py`
- text extractor: `<repo>/apps/document-generator/backend/extractors.py`
- PDF text editor: `<repo>/apps/document-generator/backend/pdf_editor.py`
- Markdown converter: `<repo>/apps/document-generator/backend/markdown_converter.py`
- spreadsheet transformer: `<repo>/apps/document-generator/backend/spreadsheet_transform.py`
- DOCX writer: `<repo>/apps/document-generator/backend/generators/docx_generator.py`
- PPTX writer: `<repo>/apps/document-generator/backend/generators/pptx_generator.py`
- PDF writer: `<repo>/apps/document-generator/backend/generators/pdf_generator.py`
- XLSX writer: `<repo>/apps/document-generator/backend/generators/xlsx_generator.py`

Do not call generator scripts directly. They are implementation details used by the CLI, MCP, and backend service.

## Output Formats

Supported formats:

- `docx`
- `pptx`
- `pdf`
- `xlsx`

Text extraction supports the same modern document formats:

- `pdf`
- `docx`
- `pptx`
- `xlsx`

Do not request `xls`; this app intentionally supports only `xlsx` for spreadsheets.

Markdown conversion supports:

- `pdf`
- `docx`
- `pptx`
- `xlsx`

Markdown conversion uses Docling. If `convert_to_markdown` reports that Docling is unavailable, the platform environment needs the `document-generator` Python extra installed.

PDF text patching uses the PyMuPDF runtime dependency. Do not create a temporary virtualenv or hand-roll PDF coordinates for ordinary text replacement; use the official `patch_pdf_text` or `modify_uploaded_document` action first.

Markdown conversion runs synchronously through the app entrypoint and accepts source files up to 10 MiB. For larger or scanned-heavy PDFs, ask the user to split or reduce the source before conversion.

## CLI Procedure

Use command id:

```text
app.document-generator.document-generator
```

From a repository shell, call the app-owned CLI surface:

```bash
./scripts/maverick app document-generator cli run document-generator --arguments-json '<json>' --json
```

Do not use `core cli run` for this app command.

Call the command with action `validate_spec` before generation when the document structure is non-trivial. Then call it again with action `generate_document`.

The generated file is written under `storage/generated/`. Report the returned `workspace_relative_path` to the user.

The CLI arguments are JSON. In a Maverick CLI tool invocation, pass the JSON object as the command arguments.

### DOCX

Use DOCX for narrative documents, letters, briefs, proposals, company profiles, reports, and documents that need headings and paragraphs.

Validate:

```json
{
  "action": "validate_spec",
  "spec": {
    "format": "docx",
    "title": "Quarterly Brief",
    "output_filename": "quarterly-brief.docx",
    "sections": [
      {"heading": "Summary", "text": "Key points for the quarter."},
      {"heading": "Next steps", "text": "Actions and owners."}
    ],
    "tables": [
      {"rows": [["Metric", "Value"], ["Revenue", "Growing"]]}
    ]
  }
}
```

Generate:

```json
{
  "action": "generate_document",
  "spec": {
    "format": "docx",
    "title": "Quarterly Brief",
    "output_filename": "quarterly-brief.docx",
    "sections": [
      {"heading": "Summary", "text": "Key points for the quarter."},
      {"heading": "Next steps", "text": "Actions and owners."}
    ],
    "tables": [
      {"rows": [["Metric", "Value"], ["Revenue", "Growing"]]}
    ]
  }
}
```

### PPTX

Use PPTX for slide decks, pitch material, meeting presentations, product walkthroughs, and executive summaries.

Generate:

```json
{
  "action": "generate_document",
  "spec": {
    "format": "pptx",
    "title": "Product Update",
    "output_filename": "product-update.pptx",
    "slides": [
      {"title": "Overview", "bullets": ["Progress this month", "Key risks", "Next priorities"]},
      {"title": "Roadmap", "bullets": ["Launch beta", "Collect feedback", "Prepare release"]}
    ]
  }
}
```

### PDF

Use PDF for fixed-layout summaries, externally shared briefs, one-page statements, and read-only deliverables.

Generate:

```json
{
  "action": "generate_document",
  "spec": {
    "format": "pdf",
    "title": "Executive Summary",
    "output_filename": "executive-summary.pdf",
    "sections": [
      {"heading": "Context", "text": "The project is entering the validation phase."},
      {"heading": "Recommendation", "text": "Proceed with the next milestone after stakeholder review."}
    ]
  }
}
```

Patch an existing workspace PDF when the user asks to replace a visible field such as a date:

```json
{
  "action": "patch_pdf_text",
  "workspace_relative_path": "storage/uploaded/file-id/contract.pdf",
  "patches": [
    {
      "match_text": "18/09/2025",
      "replacement_text": "17/06/2026",
      "occurrence": 1,
      "redact_original": true
    }
  ],
  "output_filename": "contract-2026-06-17.pdf"
}
```

For simple requests like "change the date in this uploaded PDF", use the task-level workflow:

```json
{
  "action": "modify_uploaded_document",
  "workspace_relative_path": "storage/uploaded/file-id/contract.pdf",
  "replacement_text": "17/06/2026",
  "output_filename": "contract-2026-06-17.pdf"
}
```

If the workflow returns `status: "needs_confirmation"`, ask one concise question using the returned date candidates, then call it again with `match_text` or `confirmed_match_text`.

### XLSX

Use XLSX for spreadsheets, structured data, tables, trackers, exports, financial models, and simple datasets.

Generate:

```json
{
  "action": "generate_document",
  "spec": {
    "format": "xlsx",
    "title": "Budget Tracker",
    "output_filename": "budget-tracker.xlsx",
    "sheets": [
      {
        "name": "Budget",
        "rows": [
          ["Category", "Planned", "Actual"],
          ["Design", 5000, 4200],
          ["Development", 12000, 11800]
        ]
      }
    ]
  }
}
```

Transform an existing workspace XLSX, CSV, or TSV with `spreadsheet.transform` before using direct spreadsheet libraries:

```json
{
  "action": "spreadsheet.transform",
  "target_file": "storage/generated/budget-tracker.xlsx",
  "mode": "versioned",
  "operations": [
    {
      "type": "write_cells",
      "sheet": 0,
      "cells": [
        {"row": 2, "column": "C", "value": 4200}
      ]
    }
  ]
}
```

Supported spreadsheet operations:

- `write_cells` writes explicit cell values.
- `lookup_and_copy` copies values between workbooks by key columns.
- `find_values` audits matching values without changing cells.

## MCP Procedure

Use `app.document-generator.maverick_document_generator` with the same arguments as the CLI.

For document text extraction, prefer:

- CLI command `app.document-generator.document-generator` with action `extract_text`
- MCP tool `app.document-generator.document_generator_extract_text`

Extraction inputs should identify a workspace file under `storage/uploaded/` or `storage/generated/`:

```json
{
  "action": "extract_text",
  "workspace_relative_path": "storage/uploaded/file-id/example.pdf",
  "max_chars": 50000
}
```

For PDF text patching, prefer:

- CLI command `app.document-generator.document-generator` with action `patch_pdf_text`
- MCP tool `app.document-generator.document_generator_patch_pdf_text`
- MCP tool `app.document-generator.document_generator_modify_uploaded_document` for simple uploaded-document date replacements

Expected PDF patch shape:

```json
{
  "status_code": 200,
  "status": "patched",
  "document": {
    "format": "pdf",
    "workspace_relative_path": "storage/generated/document-generator/pdf-edits/job-id/contract-2026-06-17.pdf"
  },
  "patches": [
    {
      "old_match_count": 1,
      "remaining_old_match_count": 0,
      "new_match_count": 1
    }
  ],
  "visual_diff_artifact": "storage/generated/document-generator/pdf-edits/job-id/contract-2026-06-17-verification.png"
}
```

For document-to-Markdown conversion, prefer:

- CLI command `app.document-generator.document-generator` with action `convert_to_markdown`
- MCP tool `app.document-generator.document_generator_convert_to_markdown`

Conversion inputs should identify a workspace file under `storage/uploaded/` or `storage/generated/`:

```json
{
  "action": "convert_to_markdown",
  "workspace_relative_path": "storage/uploaded/file-id/example.pdf",
  "output_filename": "example.md",
  "return_markdown": false
}
```

For spreadsheet transforms, prefer:

- CLI command `app.document-generator.document-generator` with action `spreadsheet.transform`
- MCP tool `app.document-generator.document_generator_spreadsheet_transform`

Spreadsheet transform inputs should identify files under `storage/uploaded/` or `storage/generated/`, and outputs must target `storage/generated/`:

```json
{
  "action": "spreadsheet.transform",
  "target_file": "storage/generated/output.xlsx",
  "mode": "versioned",
  "source_files": ["storage/generated/source.xlsx", "storage/generated/output.xlsx"],
  "operations": [
    {
      "type": "lookup_and_copy",
      "source": {"file": "source", "sheet": 0, "key_column": "A", "columns": ["B"]},
      "target": {"file": "output", "sheet": 0, "key_column": "A", "columns": ["C"]}
    }
  ]
}
```

Expected spreadsheet transform shape:

```json
{
  "status_code": 200,
  "status": "transformed",
  "workspace_relative_path": "storage/generated/output.v2.xlsx",
  "audit": {
    "operations": [
      {"type": "lookup_and_copy", "changed_cells": 2}
    ],
    "report_path": "storage/generated/document-generator/spreadsheet-reports/job.md"
  }
}
```

Expected conversion shape:

```json
{
  "status_code": 200,
  "document": {
    "format": "md",
    "filename": "example.md",
    "workspace_relative_path": "storage/generated/document-generator/markdown/job-id/example.md"
  },
  "markdown_path": "storage/generated/document-generator/markdown/job-id/example.md",
  "manifest_path": "data/<local_app_id>/jobs/job-id.json",
  "markdown_length": 1234
}
```

Expected extraction shape:

```json
{
  "status_code": 200,
  "document": {
    "format": "pdf",
    "filename": "example.pdf",
    "workspace_relative_path": "storage/uploaded/file-id/example.pdf"
  },
  "text": "Extracted document text...",
  "text_length": 1234,
  "truncated": false,
  "extraction": {
    "engine": "pymupdf",
    "layers": {
      "pdf_text": true,
      "overlay_text": "included",
      "ocr": false
    }
  }
}
```

For discovery or follow-up references, use:

- `app.document-generator.document_generator_reference_manifest`
- `app.document-generator.document_generator_reference_search`
- `app.document-generator.document_generator_reference_resolve`
- `app.document-generator.document_generator_reference_summarize`

## Result Handling

After generation:

1. Check `status_code`.
2. Read `document.workspace_relative_path`.
3. Confirm the file exists under `storage/generated/`.
4. Return the workspace-relative path to the user.

After PDF patching, also check `patches[].remaining_old_match_count`, `patches[].new_match_count`, and `visual_diff_artifact` when present. Prefer returning the generated PDF Storage path plus the verification result, not raw local filesystem paths.

After spreadsheet transforms, also check `audit.operations[].changed_cells`, `audit.warnings`, `sha256_before`, `sha256_after`, and `report_path`. Prefer returning the generated spreadsheet Storage path and audit summary, not raw local filesystem paths.

Expected success shape:

```json
{
  "status_code": 200,
  "document": {
    "format": "docx",
    "filename": "quarterly-brief.docx",
    "workspace_relative_path": "storage/generated/quarterly-brief.docx"
  }
}
```
