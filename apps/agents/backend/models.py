"""Agents app data model constants."""

from __future__ import annotations

import re


ROLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_TYPE_ID_PATTERN = re.compile(r"^agent-type-[a-z0-9]+(?:-[a-z0-9]+)*$")
INSTANCE_ID_PATTERN = re.compile(r"^agent-instance-[a-z0-9]+(?:-[a-z0-9]+)*$")

EXECUTION_MODE_POLICIES = {"fixed", "selectable"}
EXECUTION_MODES = {"sandbox", "full_access"}
TRACE_VERBOSITIES = {"compact", "verbose"}

DEFAULT_COMMON_PROMPT = """You are operating inside Maverick v3.

Respect workspace boundaries, prefer app-owned data surfaces over direct storage access, and use generic core runtime and MCP capabilities when they exist.
"""
