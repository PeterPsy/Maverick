"""Agents app data model constants."""

from __future__ import annotations

import re


AGENT_TYPE_ID_PATTERN = re.compile(r"^agent-type-[a-z0-9]+(?:-[a-z0-9]+)*$")
