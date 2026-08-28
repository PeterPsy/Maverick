"""One retry-safe native OpenDesign submission using supported public APIs."""

from __future__ import annotations

from base64 import b64encode
from contextlib import suppress
from typing import Any, Callable

from delegation_errors import DelegationError
from delegation_inputs import DelegationRequest, deep_link
from delegation_projection import assistant_run_projection, uploaded_file_path
from delegation_store import DelegationStore
from opendesign_target import OpenDesignTargetResolver
from opendesign_client import (
    OpenDesignClientError,
    OpenDesignProtocolError,
    validated_identifier,
)


class NativeDelegationFlow:
    """Append one visible brief and start exactly one native OpenDesign run."""

    def __init__(self, client: Any, clock_ms: Callable[[], int]) -> None:
        self.client = client
        self.clock_ms = clock_ms

    def submit(
        self,
        request: DelegationRequest,
        record: dict[str, Any],
        *,
        store: DelegationStore,
        owner: str,
        app_id: str,
    ) -> tuple[dict[str, Any], bool]:
        _assert_retry_target(request, record)
        targets = OpenDesignTargetResolver(self.client)
        project_id, created_conversation_id = targets.resolve_project(request, record)
        record = store.patch(
            request.delegation_id,
            {"od_project_id": project_id},
            owner=owner,
        )
        conversation_id = targets.resolve_conversation(
            request,
            record,
            project_id,
            created_conversation_id,
        )
        record = store.patch(
            request.delegation_id,
            {
                "od_conversation_id": conversation_id,
                "deep_link": deep_link(app_id, project_id, conversation_id),
                "status": "preparing",
            },
            owner=owner,
        )
        recovered = self._recover_run(request, project_id, conversation_id)
        if recovered["run_id"]:
            return (
                store.release(
                    request.delegation_id,
                    owner,
                    _recovered_updates(recovered),
                ),
                True,
            )

        attachments = self._upload_attachments(request, project_id)
        now = self.clock_ms()
        saved = self.client.put_message(
            project_id,
            conversation_id,
            request.message_id,
            {
                "role": "user",
                "content": request.visible_message,
                "attachments": attachments,
                "startedAt": now,
                "endedAt": now,
            },
        )
        if str(saved.get("id") or "") != request.message_id or saved.get("role") != "user":
            raise OpenDesignProtocolError("OpenDesign did not persist the delegated user message.")
        try:
            started = self.client.start_run(
                self._run_body(request, project_id, conversation_id, attachments)
            )
        except OpenDesignClientError as original:
            with suppress(OpenDesignClientError, ValueError):
                recovered = self._recover_run(request, project_id, conversation_id)
                if recovered["run_id"]:
                    return (
                        store.release(
                            request.delegation_id,
                            owner,
                            _recovered_updates(recovered),
                        ),
                        True,
                    )
            raise original
        run_id = self._validated_started_run(started, request, conversation_id)
        return (
            store.release(
                request.delegation_id,
                owner,
                {"od_run_id": run_id, "status": "queued"},
            ),
            False,
        )

    def _recover_run(
        self,
        request: DelegationRequest,
        project_id: str,
        conversation_id: str,
    ) -> dict[str, str]:
        messages = self.client.list_messages(project_id, conversation_id)
        return assistant_run_projection(messages, request.assistant_message_id)

    def _upload_attachments(
        self,
        request: DelegationRequest,
        project_id: str,
    ) -> list[dict[str, Any]]:
        native: list[dict[str, Any]] = []
        for index, attachment in enumerate(request.attachments):
            expected_path = request.attachment_path(index, attachment)
            file_record = self.client.upload_file(
                project_id,
                {
                    "name": expected_path,
                    "content": b64encode(attachment.content).decode("ascii"),
                    "encoding": "base64",
                    "overwrite": True,
                },
            )
            native.append({
                "path": uploaded_file_path(file_record, expected_path),
                "name": attachment.name,
                "kind": (
                    "image"
                    if attachment.media_type.lower().startswith("image/")
                    else "file"
                ),
                "size": len(attachment.content),
                "order": index,
            })
        return native

    @staticmethod
    def _run_body(
        request: DelegationRequest,
        project_id: str,
        conversation_id: str,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "message": request.visible_message,
            "currentPrompt": request.visible_message,
            "projectId": project_id,
            "conversationId": conversation_id,
            "sessionMode": "design",
            "assistantMessageId": request.assistant_message_id,
            "clientRequestId": request.client_request_id,
            "attachments": attachments,
        }
        for source, target in (
            ("agent_id", "agentId"),
            ("model", "model"),
            ("reasoning", "reasoning"),
        ):
            value = getattr(request, source)
            if value:
                body[target] = value
        return body

    @staticmethod
    def _validated_started_run(
        started: dict[str, Any],
        request: DelegationRequest,
        conversation_id: str,
    ) -> str:
        run_id = validated_identifier(started.get("runId"), label="OpenDesign run id")
        returned_conversation = str(started.get("conversationId") or "")
        returned_assistant = str(started.get("assistantMessageId") or "")
        if returned_conversation and returned_conversation != conversation_id:
            raise OpenDesignProtocolError("OpenDesign returned a different conversation id.")
        if returned_assistant and returned_assistant != request.assistant_message_id:
            raise OpenDesignProtocolError("OpenDesign returned a different assistant message id.")
        return run_id


def _assert_retry_target(
    request: DelegationRequest,
    record: dict[str, Any],
) -> None:
    if request.project_id and record.get("od_project_id") not in {
        None,
        "",
        request.project_id,
    }:
        raise DelegationError(
            "idempotency_key_reused",
            "The idempotency key is already bound to another OpenDesign project.",
            status_code=409,
        )
    if request.conversation_id and record.get("od_conversation_id") not in {
        None,
        "",
        request.conversation_id,
    }:
        raise DelegationError(
            "idempotency_key_reused",
            "The idempotency key is already bound to another OpenDesign conversation.",
            status_code=409,
        )


def _recovered_updates(projection: dict[str, str]) -> dict[str, Any]:
    status = projection["status"] if projection["status"] != "unknown" else "queued"
    return {
        "od_run_id": projection["run_id"],
        "status": status,
        "event_cursor": projection["event_cursor"],
    }
