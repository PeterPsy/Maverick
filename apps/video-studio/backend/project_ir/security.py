"""Recursive fail-closed security profile for declarative Project IR."""

from __future__ import annotations

import re
from typing import Any

from .errors import ValidationIssue, issue


FORBIDDEN_KEY_PARTS = (
    "api_key",
    "command",
    "credential",
    "expression",
    "filesystem",
    "html",
    "markup",
    "password",
    "path",
    "script",
    "secret",
    "shader",
    "shell",
    "token",
    "url",
)
REMOTE_SCHEME = re.compile(r"(?i)(?:https?|ftp|file|ssh)://|data:")
HOST_PATH = re.compile(r"(?:^|[\s\"'(`])(?:/|~(?:/|$)|[A-Za-z]:[\\/])")
MARKUP = re.compile(r"(?s)<\s*/?\s*[A-Za-z][^>]*>")


def security_issues(value: object) -> list[ValidationIssue]:
    problems: list[ValidationIssue] = []
    _scan(value, "", problems)
    return problems


def _scan(value: Any, path: str, problems: list[ValidationIssue]) -> None:
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            child_path = f"{path}/{_escape(str(key))}"
            if not isinstance(key, str):
                problems.append(issue("object_key_invalid", path, "Project IR object keys must be strings."))
                continue
            normalized = key.lower().replace("-", "_")
            if any(part in normalized for part in FORBIDDEN_KEY_PARTS):
                problems.append(
                    issue(
                        "active_content_field_forbidden",
                        child_path,
                        "Project IR contains a forbidden active-content or authority field.",
                    )
                )
            _scan(value[key], child_path, problems)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan(item, f"{path}/{index}", problems)
        return
    if not isinstance(value, str):
        return
    if REMOTE_SCHEME.search(value.strip()):
        problems.append(issue("remote_reference_forbidden", path, "Remote URLs are forbidden in Project IR."))
    if HOST_PATH.search(value.strip()) or "../" in value or "..\\" in value:
        problems.append(issue("host_path_forbidden", path, "Host and traversing paths are forbidden in Project IR."))
    if MARKUP.search(value):
        problems.append(issue("active_markup_forbidden", path, "Markup is forbidden in Project IR text."))
    if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
        problems.append(issue("control_character_forbidden", path, "Control characters are forbidden in Project IR text."))


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
