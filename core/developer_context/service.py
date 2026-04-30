"""Read-only canonical developer context exposed by the core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeveloperContextDocument:
    """Describe one canonical developer document."""

    doc_id: str
    title: str
    summary: str
    source_path: str


DOCUMENTS: tuple[DeveloperContextDocument, ...] = (
    DeveloperContextDocument(
        doc_id="agents_working_agreement",
        title="Agents Working Agreement",
        summary="Repository workflow, engineering rules, and coding discipline for Maverick.",
        source_path="AGENTS.md",
    ),
    DeveloperContextDocument(
        doc_id="core_architecture",
        title="Core Architecture",
        summary="Canonical architecture for the headless Maverick core and platform boundaries.",
        source_path="docs/architecture/core_architecture.md",
    ),
    DeveloperContextDocument(
        doc_id="workspace_root_architecture",
        title="Workspace Root Architecture",
        summary="Canonical rules for workspace roots, storage layout, and workspace-owned material.",
        source_path="docs/architecture/workspace_root_architecture.md",
    ),
    DeveloperContextDocument(
        doc_id="app_contract_architecture",
        title="App Contract Architecture",
        summary="Canonical app contract model, ownership rules, and app/core integration surfaces.",
        source_path="docs/architecture/app_contract_architecture.md",
    ),
)


class DeveloperContextError(ValueError):
    """Raised when the requested canonical developer context is invalid."""


def list_documents() -> list[dict[str, str]]:
    """Return metadata for the canonical developer context documents."""
    return [
        {
            "doc_id": item.doc_id,
            "title": item.title,
            "summary": item.summary,
            "source_path": item.source_path,
        }
        for item in DOCUMENTS
    ]


def read_document(*, doc_id: str, start_path: Path | None) -> dict[str, str]:
    """Return the canonical document metadata and full text for one document."""
    normalized = str(doc_id or "").strip()
    document = next((item for item in DOCUMENTS if item.doc_id == normalized), None)
    if document is None:
        raise DeveloperContextError(f"Unknown developer context doc_id `{normalized}`.")
    repository_root = (start_path or Path.cwd()).resolve()
    source_file = repository_root / document.source_path
    if not source_file.is_file():
        raise DeveloperContextError(f"Developer context source `{document.source_path}` is not available.")
    return {
        "doc_id": document.doc_id,
        "title": document.title,
        "summary": document.summary,
        "source_path": document.source_path,
        "content": source_file.read_text(encoding="utf-8"),
    }
