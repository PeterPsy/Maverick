"""Retry-stable selection or creation of native OpenDesign chat targets."""

from __future__ import annotations

from typing import Any

from delegation_errors import DelegationError
from delegation_inputs import DelegationRequest
from opendesign_client import (
    OpenDesignNotFound,
    OpenDesignProtocolError,
    OpenDesignRequestFailed,
    validated_identifier,
)


class OpenDesignTargetResolver:
    """Resolve a project and conversation without creating parallel app state."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def resolve_project(
        self,
        request: DelegationRequest,
        record: dict[str, Any],
    ) -> tuple[str, str]:
        project_id = str(
            record.get("od_project_id")
            or request.project_id
            or request.deterministic_project_id
        )
        try:
            project = self.client.get_project(project_id)
            _validate_project(project, project_id)
            return project_id, ""
        except OpenDesignNotFound:
            if request.project_id:
                raise DelegationError(
                    "opendesign_project_not_found",
                    "The selected OpenDesign project was not found.",
                    status_code=404,
                )
        body = {
            "id": project_id,
            "name": request.project_name,
            "metadata": {
                "kind": "prototype",
                "maverickIntegration": "design-studio",
            },
            "skipDiscoveryBrief": True,
            "conversationMode": "design",
        }
        try:
            created = self.client.create_project(body)
        except OpenDesignRequestFailed:
            project = self.client.get_project(project_id)
            _validate_project(project, project_id)
            return project_id, ""
        project = created.get("project")
        if not isinstance(project, dict):
            raise OpenDesignProtocolError("OpenDesign returned an invalid created project.")
        _validate_project(project, project_id)
        conversation_id = created.get("conversationId")
        if conversation_id:
            conversation_id = validated_identifier(
                conversation_id,
                label="OpenDesign conversation id",
            )
        return project_id, str(conversation_id or "")

    def resolve_conversation(
        self,
        request: DelegationRequest,
        record: dict[str, Any],
        project_id: str,
        created_conversation_id: str,
    ) -> str:
        recorded = str(record.get("od_conversation_id") or "")
        requested = request.conversation_id
        if created_conversation_id and not recorded and not requested:
            return created_conversation_id
        conversations = self.client.list_conversations(project_id)
        if recorded or requested:
            selected = recorded or requested
            if any(str(item.get("id") or "") == selected for item in conversations):
                return validated_identifier(selected, label="OpenDesign conversation id")
            raise DelegationError(
                "opendesign_conversation_not_found",
                "The selected OpenDesign conversation was not found in the project.",
                status_code=404,
            )
        if request.new_conversation:
            matching = [
                item
                for item in conversations
                if item.get("title") == request.conversation_title
            ]
            if matching:
                return _conversation_id(_earliest(matching))
            return self._create_conversation(project_id, request.conversation_title)
        if conversations:
            return _conversation_id(_earliest(conversations))
        return self._create_conversation(project_id, request.conversation_title)

    def _create_conversation(self, project_id: str, title: str) -> str:
        conversation = self.client.create_conversation(
            project_id,
            {"title": title, "sessionMode": "design"},
        )
        return _conversation_id(conversation)


def _validate_project(project: dict[str, Any], expected_id: str) -> None:
    if validated_identifier(project.get("id"), label="OpenDesign project id") != expected_id:
        raise OpenDesignProtocolError("OpenDesign project identity mismatch.")


def _conversation_id(conversation: dict[str, Any]) -> str:
    return validated_identifier(
        conversation.get("id"),
        label="OpenDesign conversation id",
    )


def _earliest(conversations: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        conversations,
        key=_conversation_order,
    )


def _conversation_order(item: dict[str, Any]) -> tuple[int, float | str, str]:
    created = item.get("createdAt")
    if isinstance(created, (int, float)) and not isinstance(created, bool):
        return (0, float(created), str(item.get("id") or ""))
    return (1, str(created or ""), str(item.get("id") or ""))
