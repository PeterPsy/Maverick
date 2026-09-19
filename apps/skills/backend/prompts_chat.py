"""Bounded public prompts.chat lookup and confirmed skill import."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from urllib.parse import quote

from prompts_chat_client import HttpTransport, PromptsChatError, PublicPromptsChatMcpClient
from store import (
    SkillsValidationError,
    get_skill,
    parse_skill_markdown,
    skill_dir,
    skills_root,
)


MAX_SEARCH_RESULTS = 5
MAX_PROMPT_BYTES = 256 * 1024
MAX_SKILL_FILES = 64
MAX_SKILL_FILE_BYTES = 256 * 1024
MAX_SKILL_TOTAL_BYTES = 768 * 1024

class PromptsChatClient:
    """Small MCP client restricted to the four public read operations."""

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._mcp = PublicPromptsChatMcpClient(transport)

    def search_prompts(self, query: str, limit: int) -> dict:
        payload = self._mcp.call("search_prompts", {"query": _query(query), "limit": _limit(limit)})
        prompts = payload.get("prompts") if isinstance(payload.get("prompts"), list) else []
        return {
            "query": _query(query),
            "content_trust": "untrusted_external",
            "prompts": [_prompt_summary(item) for item in prompts[: _limit(limit)] if isinstance(item, dict)],
        }

    def get_prompt(self, remote_id: str) -> dict:
        return {
            "content_trust": "untrusted_external",
            **_prompt_detail(self._mcp.call("get_prompt", {"id": _remote_id(remote_id)})),
        }

    def search_skills(self, query: str, limit: int) -> dict:
        payload = self._mcp.call("search_skills", {"query": _query(query), "limit": _limit(limit)})
        skills = payload.get("skills") if isinstance(payload.get("skills"), list) else []
        return {
            "query": _query(query),
            "content_trust": "untrusted_external",
            "skills": [_skill_summary(item) for item in skills[: _limit(limit)] if isinstance(item, dict)],
        }

    def get_skill(self, remote_id: str) -> dict:
        return {
            "content_trust": "untrusted_external",
            **_skill_detail(self._mcp.call("get_skill", {"id": _remote_id(remote_id)})),
        }


def install_remote_skill(
    data_root: Path,
    remote_skill: dict,
    *,
    local_id: str,
    expected_content_sha256: str,
) -> dict:
    """Install the exact reviewed multi-file skill without overwriting local data."""
    expected = str(expected_content_sha256 or "").strip().lower()
    actual = str(remote_skill.get("content_sha256") or "")
    if len(expected) != 64 or expected != actual:
        raise PromptsChatError(
            "prompts_chat_confirmation_stale",
            "The reviewed skill content no longer matches the remote skill.",
            status_code=409,
        )
    destination = skill_dir(data_root, local_id)
    if get_skill(data_root, local_id) is not None or destination.exists():
        raise PromptsChatError(
            "skill_already_exists",
            f"Workspace skill `{local_id}` already exists.",
            status_code=409,
        )
    files = remote_skill.get("files") if isinstance(remote_skill.get("files"), list) else []
    file_payloads = _validated_skill_files(files, skill_id=local_id)
    root = skills_root(data_root)
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{local_id}-", dir=root))
    installed = False
    try:
        for filename, content in file_payloads:
            target = temporary.joinpath(*PurePosixPath(filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        os.replace(temporary, destination)
        installed = True
    finally:
        if not installed:
            shutil.rmtree(temporary, ignore_errors=True)
    saved = get_skill(data_root, local_id)
    if saved is None:
        raise SkillsValidationError(f"Imported skill `{local_id}` could not be read after installation.")
    return {
        "skill": saved,
        "remote_id": remote_skill["id"],
        "content_sha256": actual,
        "installed_files": [filename for filename, _content in file_payloads],
    }


def _query(value: str) -> str:
    query = " ".join(str(value or "").split()).strip()
    if not query or len(query) > 240:
        raise PromptsChatError("invalid_query", "query must contain between 1 and 240 characters.", status_code=400)
    return query


def _limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise PromptsChatError("invalid_limit", "limit must be an integer.", status_code=400) from None
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise PromptsChatError("invalid_limit", f"limit must be between 1 and {MAX_SEARCH_RESULTS}.", status_code=400)
    return limit


def _remote_id(value: str) -> str:
    remote_id = str(value or "").strip()
    if not remote_id or len(remote_id) > 200 or any(ord(character) < 32 for character in remote_id):
        raise PromptsChatError("invalid_remote_id", "remote_id is invalid.", status_code=400)
    return remote_id


def _text(item: dict, key: str, *, maximum: int) -> str:
    value = str(item.get(key) or "").strip()
    return value[:maximum]


def _author(item: dict) -> str:
    author = item.get("author")
    if isinstance(author, dict):
        return _text(author, "username", maximum=160) or _text(author, "name", maximum=160)
    return str(author or "").strip()[:160]


def _public_link(item: dict) -> str:
    remote_id = _remote_id(item.get("id"))
    slug = _text(item, "slug", maximum=200)
    suffix = f"_{quote(slug, safe='-')}" if slug else ""
    return f"https://prompts.chat/prompts/{quote(remote_id, safe='')}{suffix}"


def _prompt_summary(item: dict) -> dict:
    content = str(item.get("content") or "").strip()
    return {
        "id": _remote_id(item.get("id")),
        "title": _text(item, "title", maximum=240),
        "description": _text(item, "description", maximum=500),
        "preview": content[:320],
        "author": _author(item),
        "link": _public_link(item),
    }


def _prompt_detail(item: dict) -> dict:
    content = str(item.get("content") or "")
    if not content or len(content.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise PromptsChatError("prompts_chat_prompt_invalid", "The remote prompt is empty or too large.")
    return {**_prompt_summary(item), "content": content}


def _skill_summary(item: dict) -> dict:
    filenames = item.get("fileNames") if isinstance(item.get("fileNames"), list) else []
    return {
        "id": _remote_id(item.get("id")),
        "slug": _text(item, "slug", maximum=200),
        "title": _text(item, "title", maximum=240),
        "description": _text(item, "description", maximum=500),
        "author": _author(item),
        "files": [str(value)[:240] for value in filenames[:MAX_SKILL_FILES]],
        "link": _public_link(item),
    }


def _skill_detail(item: dict) -> dict:
    summary = _skill_summary(item)
    files = item.get("files") if isinstance(item.get("files"), list) else []
    validated = _validated_skill_files(files, skill_id=summary["slug"] or "remote-skill")
    normalized_files = [{"filename": filename, "content": content} for filename, content in validated]
    digest_payload = json.dumps(
        normalized_files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        **summary,
        "updated_at": _text(item, "updatedAt", maximum=80),
        "files": normalized_files,
        "content_sha256": hashlib.sha256(digest_payload).hexdigest(),
    }


def _validated_skill_files(files: list, *, skill_id: str) -> list[tuple[str, str]]:
    if not files or len(files) > MAX_SKILL_FILES:
        raise PromptsChatError("prompts_chat_skill_invalid", "The remote skill has no files or too many files.")
    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    total_bytes = 0
    for item in files:
        if not isinstance(item, dict):
            raise PromptsChatError("prompts_chat_skill_invalid", "The remote skill contains an invalid file.")
        filename = str(item.get("filename") or "").strip()
        path = PurePosixPath(filename)
        if (
            not filename
            or "\\" in filename
            or any(ord(character) < 32 for character in filename)
            or path.is_absolute()
            or path.as_posix() != filename
            or len(path.parts) > 8
            or any(part in {"", ".", ".."} for part in path.parts)
            or len(filename) > 240
            or filename in seen
        ):
            raise PromptsChatError("prompts_chat_skill_invalid", "The remote skill contains an unsafe file path.")
        content = item.get("content")
        if not isinstance(content, str):
            raise PromptsChatError("prompts_chat_skill_invalid", "The remote skill contains a non-text file.")
        size = len(content.encode("utf-8"))
        total_bytes += size
        if size > MAX_SKILL_FILE_BYTES or total_bytes > MAX_SKILL_TOTAL_BYTES:
            raise PromptsChatError("prompts_chat_skill_invalid", "The remote skill is too large.")
        seen.add(filename)
        normalized.append((filename, content))
    paths = [PurePosixPath(filename) for filename, _content in normalized]
    if any(left in right.parents for left in paths for right in paths if left != right):
        raise PromptsChatError("prompts_chat_skill_invalid", "The remote skill contains conflicting file paths.")
    skill_markdown = next((content for filename, content in normalized if filename == "SKILL.md"), None)
    if skill_markdown is None:
        raise PromptsChatError("prompts_chat_skill_invalid", "The remote skill does not contain SKILL.md.")
    try:
        parse_skill_markdown(skill_markdown, skill_id=skill_id)
    except SkillsValidationError as error:
        raise PromptsChatError("prompts_chat_skill_invalid", str(error)) from None
    return sorted(normalized, key=lambda item: item[0])
