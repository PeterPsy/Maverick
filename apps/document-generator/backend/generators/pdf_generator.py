"""Small PDF generator for text documents."""

from __future__ import annotations

from pathlib import Path

from generators.common import section_blocks
from models import DocumentSpec


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def generate_pdf(spec: DocumentSpec, target: Path) -> None:
    lines = [spec.title, ""]
    for heading, text in section_blocks(spec.sections):
        if heading:
            lines.append(heading)
        if text:
            lines.extend(text.splitlines() or [text])
        lines.append("")
    stream_lines = ["BT", "/F1 18 Tf", "72 760 Td", f"({_pdf_escape(lines[0])}) Tj", "/F1 11 Tf"]
    for line in lines[1:]:
        stream_lines.append("0 -18 Td")
        stream_lines.append(f"({_pdf_escape(line[:120])}) Tj")
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode("ascii"))
        content.extend(obj)
        content.extend(b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    content.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(content))
