#!/usr/bin/env python3
"""Validate inline <script> blocks inside one or more HTML files with Node."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path


class InlineScriptParser(HTMLParser):
    """Collect inline JavaScript blocks while skipping external script tags."""

    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._chunks: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attributes = dict(attrs)
        if attributes.get("src"):
            self._capture = False
            self._chunks = []
            return
        script_type = (attributes.get("type") or "").strip().lower()
        if script_type and script_type not in {"text/javascript", "application/javascript", "module"}:
            self._capture = False
            self._chunks = []
            return
        self._capture = True
        self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script":
            return
        if self._capture:
            self.scripts.append("".join(self._chunks))
        self._capture = False
        self._chunks = []


def extract_inline_scripts(html_path: Path) -> list[str]:
    parser = InlineScriptParser()
    parser.feed(html_path.read_text(encoding="utf-8"))
    return [script for script in parser.scripts if script.strip()]


def check_script_syntax(script: str, *, html_path: Path, index: int) -> str | None:
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as handle:
        temp_path = Path(handle.name)
        handle.write(script)
    try:
        result = subprocess.run(
            ["node", "--check", str(temp_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        temp_path.unlink(missing_ok=True)
    if result.returncode == 0:
        return None
    stderr = result.stderr.strip() or result.stdout.strip() or "Unknown syntax error."
    return f"{html_path}: inline <script> #{index} failed syntax check\n{stderr}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate inline <script> blocks inside HTML files with node --check.",
    )
    parser.add_argument("html_files", nargs="+", help="HTML files to inspect.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    failures: list[str] = []
    checked = 0

    for raw_path in args.html_files:
        html_path = Path(raw_path).resolve()
        if not html_path.is_file():
            failures.append(f"{html_path}: file not found")
            continue
        for index, script in enumerate(extract_inline_scripts(html_path), start=1):
            checked += 1
            error = check_script_syntax(script, html_path=html_path, index=index)
            if error is not None:
                failures.append(error)

    if failures:
        print("\n\n".join(failures), file=sys.stderr)
        return 1

    print(f"Validated {checked} inline <script> block(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
