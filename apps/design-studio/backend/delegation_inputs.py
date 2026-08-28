"""Validation and deterministic identities for OpenDesign delegations."""

from __future__ import annotations

from base64 import b64decode
import binascii
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import quote

from opendesign_client import validated_identifier


MAX_BRIEF_CHARS = 100_000
MAX_ATTACHMENTS = 8
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class DelegationInputError(ValueError):
    """An explicit delegation input is invalid or not authorized."""


@dataclass(frozen=True)
class AuthorizedAttachment:
    name: str
    safe_name: str
    media_type: str
    content: bytes


@dataclass(frozen=True)
class DelegationRequest:
    delegation_id: str
    digest: str
    request_fingerprint: str
    brief: str
    project_id: str
    conversation_id: str
    project_name: str
    new_conversation: bool
    agent_id: str
    model: str
    reasoning: str
    attachments: tuple[AuthorizedAttachment, ...]

    @property
    def message_id(self) -> str:
        return f"mav_user_{self.digest[:24]}"

    @property
    def assistant_message_id(self) -> str:
        return f"mav_assistant_{self.digest[:24]}"

    @property
    def client_request_id(self) -> str:
        return f"mav_delegate_{self.digest[:32]}"

    @property
    def deterministic_project_id(self) -> str:
        return f"od_mav_{self.digest[:24]}"

    @property
    def conversation_title(self) -> str:
        return f"Maverick delegation {self.delegation_id[-8:]}"

    @property
    def visible_message(self) -> str:
        return f"Brief delegated by Maverick\n\n{self.brief}"

    def attachment_path(self, index: int, attachment: AuthorizedAttachment) -> str:
        return f"delegated/{self.delegation_id}/{index + 1:02d}-{attachment.safe_name}"


def parse_delegation_request(workspace_id: str, arguments: dict[str, Any]) -> DelegationRequest:
    """Validate explicit inputs and derive retry-stable native identities."""
    workspace = str(workspace_id or "").strip()
    if not workspace:
        raise DelegationInputError("A workspace context is required.")
    idempotency_key = _bounded_text(
        arguments.get("idempotency_key"),
        label="idempotency_key",
        maximum=256,
        required=True,
        single_line=True,
    )
    digest = sha256(f"{workspace}\0{idempotency_key}".encode("utf-8")).hexdigest()
    brief = _bounded_text(
        arguments.get("brief"),
        label="brief",
        maximum=MAX_BRIEF_CHARS,
        required=True,
    )
    project_id = _optional_identifier(arguments.get("project_id"), "OpenDesign project id")
    conversation_id = _optional_identifier(
        arguments.get("conversation_id"),
        "OpenDesign conversation id",
    )
    if conversation_id and not project_id:
        raise DelegationInputError("conversation_id requires an explicit project_id.")
    new_conversation = arguments.get("new_conversation", False)
    if not isinstance(new_conversation, bool):
        raise DelegationInputError("new_conversation must be a boolean.")
    if conversation_id and new_conversation:
        raise DelegationInputError("conversation_id and new_conversation are mutually exclusive.")
    project_name = _bounded_text(
        arguments.get("project_name"),
        label="project_name",
        maximum=200,
        required=False,
        single_line=True,
    ) or f"Delegated design {digest[:8]}"
    attachments = _attachments(arguments.get("attachments"))
    agent_id = _selector(arguments.get("agent_id"), "agent_id")
    model = _selector(arguments.get("model"), "model")
    reasoning = _selector(arguments.get("reasoning"), "reasoning", maximum=64)
    fingerprint = _request_fingerprint(
        brief=brief,
        project_id=project_id,
        conversation_id=conversation_id,
        project_name=project_name,
        new_conversation=new_conversation,
        agent_id=agent_id,
        model=model,
        reasoning=reasoning,
        attachments=attachments,
    )
    return DelegationRequest(
        delegation_id=f"dlg_{digest[:32]}",
        digest=digest,
        request_fingerprint=fingerprint,
        brief=brief,
        project_id=project_id,
        conversation_id=conversation_id,
        project_name=project_name,
        new_conversation=new_conversation,
        agent_id=agent_id,
        model=model,
        reasoning=reasoning,
        attachments=attachments,
    )


def deep_link(app_id: str, project_id: str, conversation_id: str) -> str:
    """Build the exact native conversation route mounted by Maverick."""
    app = quote(str(app_id or "design-studio"), safe="")
    project = quote(validated_identifier(project_id, label="OpenDesign project id"), safe="")
    conversation = quote(
        validated_identifier(conversation_id, label="OpenDesign conversation id"),
        safe="",
    )
    return f"/app/{app}/projects/{project}/conversations/{conversation}"


def _attachments(value: object) -> tuple[AuthorizedAttachment, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_ATTACHMENTS:
        raise DelegationInputError(f"attachments must contain at most {MAX_ATTACHMENTS} items.")
    attachments: list[AuthorizedAttachment] = []
    total = 0
    for item in value:
        if not isinstance(item, dict) or item.get("authorized") is not True:
            raise DelegationInputError("Every attachment requires explicit authorized=true.")
        name = _bounded_text(
            item.get("name"),
            label="attachment name",
            maximum=180,
            required=True,
            single_line=True,
        )
        if PurePosixPath(name).name != name or "\\" in name or name in {".", ".."}:
            raise DelegationInputError("Attachment names must be plain file names.")
        encoded = item.get("content_base64")
        if not isinstance(encoded, str):
            raise DelegationInputError("Every attachment requires content_base64.")
        try:
            content = b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise DelegationInputError("Attachment content_base64 is invalid.") from error
        if not content:
            raise DelegationInputError("Attachments cannot be empty.")
        total += len(content)
        if total > MAX_ATTACHMENT_BYTES:
            raise DelegationInputError("Authorized attachments exceed the 10 MiB delegation limit.")
        media_type = _bounded_text(
            item.get("media_type"),
            label="attachment media_type",
            maximum=100,
            required=False,
            single_line=True,
        ) or "application/octet-stream"
        safe_name = SAFE_FILENAME_PATTERN.sub("-", name).strip(".-") or "attachment"
        attachments.append(AuthorizedAttachment(name, safe_name[:160], media_type, content))
    return tuple(attachments)


def _request_fingerprint(
    *,
    brief: str,
    project_id: str,
    conversation_id: str,
    project_name: str,
    new_conversation: bool,
    agent_id: str,
    model: str,
    reasoning: str,
    attachments: tuple[AuthorizedAttachment, ...],
) -> str:
    """Bind an idempotency key to the complete normalized semantic request."""
    payload = {
        "schema_version": "1",
        "brief": brief,
        "project_id": project_id,
        "conversation_id": conversation_id,
        "project_name": project_name,
        "new_conversation": new_conversation,
        "agent_id": agent_id,
        "model": model,
        "reasoning": reasoning,
        "attachments": [
            {
                "name": attachment.name,
                "safe_name": attachment.safe_name,
                "media_type": attachment.media_type,
                "content_sha256": sha256(attachment.content).hexdigest(),
            }
            for attachment in attachments
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _optional_identifier(value: object, label: str) -> str:
    if value is None or not str(value).strip():
        return ""
    try:
        return validated_identifier(value, label=label)
    except ValueError as error:
        raise DelegationInputError(str(error)) from error


def _selector(value: object, label: str, *, maximum: int = 200) -> str:
    return _bounded_text(
        value,
        label=label,
        maximum=maximum,
        required=False,
        single_line=True,
    )


def _bounded_text(
    value: object,
    *,
    label: str,
    maximum: int,
    required: bool,
    single_line: bool = False,
) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise DelegationInputError(f"{label} must be a string.")
    if required and not text:
        raise DelegationInputError(f"{label} is required.")
    if len(text) > maximum:
        raise DelegationInputError(f"{label} exceeds {maximum} characters.")
    if "\x00" in text or (single_line and any(character in text for character in "\r\n")):
        raise DelegationInputError(f"{label} contains invalid control characters.")
    return text
