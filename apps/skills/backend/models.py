"""Models and defaults for the Skills app."""

from __future__ import annotations

import re


SKILL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
SCHEMA_VERSION = "1"

DEFAULT_SKILL_CONTENT = """Use this skill when a Maverick agent needs a focused, repeatable procedure.

## Workflow

1. State when this skill applies.
2. Use the official app, MCP, CLI, or backend surface for real operations.
3. Keep output concise and actionable.
"""
