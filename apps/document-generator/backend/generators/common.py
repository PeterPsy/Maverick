"""Shared helpers for document generators."""

from __future__ import annotations

from html import escape
from typing import Any


def xml_text(value: Any) -> str:
    return escape(str(value), quote=False)


def xml_attr(value: Any) -> str:
    return escape(str(value), quote=True)


def section_blocks(sections: list[dict[str, Any]]) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for section in sections:
        heading = str(section.get("heading") or section.get("title") or "").strip()
        text = str(section.get("text") or section.get("body") or "").strip()
        if heading or text:
            blocks.append((heading, text))
    return blocks


def table_rows(tables: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for table in tables:
        raw_rows = table.get("rows")
        if isinstance(raw_rows, list):
            for row in raw_rows:
                if isinstance(row, list):
                    rows.append(row)
    return rows
