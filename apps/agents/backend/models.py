"""Agents app data model constants."""

from __future__ import annotations

import re


ROLE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_TYPE_ID_PATTERN = re.compile(r"^agent-type-[a-z0-9]+(?:-[a-z0-9]+)*$")

TRACE_VERBOSITIES = {"compact", "verbose"}

DEFAULT_COMMON_PROMPT = ""
