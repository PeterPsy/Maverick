---
name: document-generator-docs
description: "Use the Document Generator app CLI or MCP tool to create DOCX, PPTX, PDF, and XLSX files in workspace generated storage."
---

# Document Generator Docs

Use this skill when a user asks an agent to create a document file.

## App Scripts

The app exposes one official CLI command and one official MCP tool. Use those surfaces for real work.

Implementation scripts behind those surfaces:

- CLI entrypoint: `<repo>/apps/document-generator/cli/app_cli.py`
- MCP entrypoint: `<repo>/apps/document-generator/mcp/server.py`
- shared service: `<repo>/apps/document-generator/backend/service.py`
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

Do not request `xls`; this app intentionally supports only `xlsx` for spreadsheets.

## CLI Procedure

Use command id:

```text
app.document-generator.document-generator
```

Call the command with action `validate_spec` before generation when the document structure is non-trivial. Then call it again with action `generate_document`.

The generated file is written under `storage/generated/`. Report the returned `workspace_relative_path` to the user.

The CLI arguments are JSON. In a Maverick CLI tool invocation, pass the JSON object as the command arguments. If you need a shell smoke test inside the repository, invoke the core CLI service rather than the private generator scripts.

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

## MCP Procedure

Use `app.document-generator.maverick_document_generator` with the same arguments as the CLI.

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
