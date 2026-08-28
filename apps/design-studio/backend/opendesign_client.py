"""Bounded client for the supported public OpenDesign delegation APIs."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from core.app_sdk.app_sidecar import AppSidecarError, app_sidecar


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$")


class OpenDesignClientError(RuntimeError):
    """Base failure for the public OpenDesign client."""


class OpenDesignUnavailable(OpenDesignClientError):
    """The invocation-scoped OpenDesign capability is unavailable."""


class OpenDesignNotFound(OpenDesignClientError):
    """The requested native OpenDesign resource does not exist."""


class OpenDesignRequestFailed(OpenDesignClientError):
    """OpenDesign rejected a supported public request."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"OpenDesign returned HTTP {status_code}.")


class OpenDesignProtocolError(OpenDesignClientError):
    """OpenDesign returned a response outside its supported public contract."""


def validated_identifier(value: object, *, label: str) -> str:
    """Validate one OpenDesign identifier before using it in a route."""
    identifier = str(value or "").strip()
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"A valid {label} is required.")
    return identifier


def identifier_path(value: object, *, label: str) -> str:
    """Return a validated, percent-encoded path segment."""
    return quote(validated_identifier(value, label=label), safe="")


class OpenDesignClient:
    """Use only the core-issued, invocation-scoped OpenDesign broker."""

    def __init__(self, payload: Any, *, transport: Any | None = None) -> None:
        try:
            self._transport = transport or app_sidecar(payload, "opendesign")
        except AppSidecarError as error:
            raise OpenDesignUnavailable("OpenDesign delegation is unavailable.") from error

    def list_projects(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/projects")
        return _object_list(payload, "projects")

    def get_project(self, project_id: str) -> dict[str, Any]:
        path_id = identifier_path(project_id, label="OpenDesign project id")
        payload = self._request("GET", f"/api/projects/{path_id}")
        project = payload.get("project")
        if not isinstance(project, dict):
            raise OpenDesignProtocolError("OpenDesign returned an invalid project.")
        return project

    def create_project(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/projects", body)

    def list_conversations(self, project_id: str) -> list[dict[str, Any]]:
        project = identifier_path(project_id, label="OpenDesign project id")
        payload = self._request("GET", f"/api/projects/{project}/conversations")
        return _object_list(payload, "conversations")

    def create_conversation(self, project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        project = identifier_path(project_id, label="OpenDesign project id")
        payload = self._request("POST", f"/api/projects/{project}/conversations", body)
        conversation = payload.get("conversation")
        if not isinstance(conversation, dict):
            raise OpenDesignProtocolError("OpenDesign returned an invalid conversation.")
        return conversation

    def list_messages(self, project_id: str, conversation_id: str) -> list[dict[str, Any]]:
        project = identifier_path(project_id, label="OpenDesign project id")
        conversation = identifier_path(conversation_id, label="OpenDesign conversation id")
        payload = self._request(
            "GET",
            f"/api/projects/{project}/conversations/{conversation}/messages",
        )
        return _object_list(payload, "messages")

    def put_message(
        self,
        project_id: str,
        conversation_id: str,
        message_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        project = identifier_path(project_id, label="OpenDesign project id")
        conversation = identifier_path(conversation_id, label="OpenDesign conversation id")
        message = identifier_path(message_id, label="OpenDesign message id")
        payload = self._request(
            "PUT",
            f"/api/projects/{project}/conversations/{conversation}/messages/{message}",
            body,
        )
        saved = payload.get("message")
        if not isinstance(saved, dict):
            raise OpenDesignProtocolError("OpenDesign returned an invalid message.")
        return saved

    def upload_file(self, project_id: str, body: dict[str, Any]) -> dict[str, Any]:
        project = identifier_path(project_id, label="OpenDesign project id")
        payload = self._request("POST", f"/api/projects/{project}/files", body)
        file_record = payload.get("file")
        if not isinstance(file_record, dict):
            raise OpenDesignProtocolError("OpenDesign returned an invalid file record.")
        return file_record

    def start_run(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/runs", body)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = identifier_path(run_id, label="OpenDesign run id")
        return self._request("GET", f"/api/runs/{run}")

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = identifier_path(run_id, label="OpenDesign run id")
        return self._request("POST", f"/api/runs/{run}/cancel", {})

    def get_result_package(self, run_id: str) -> dict[str, Any]:
        run = identifier_path(run_id, label="OpenDesign run id")
        return self._request("GET", f"/api/runs/{run}/result-package")

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._transport.request(
                method,
                path,
                headers={"accept": "application/json"},
                **({"json_body": body} if body is not None else {}),
            )
        except AppSidecarError as error:
            raise OpenDesignUnavailable("OpenDesign delegation is unavailable.") from error
        if response.status_code == 404:
            raise OpenDesignNotFound("OpenDesign resource not found.")
        if response.status_code >= 400:
            raise OpenDesignRequestFailed(response.status_code)
        try:
            payload = response.json()
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenDesignProtocolError("OpenDesign returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise OpenDesignProtocolError("OpenDesign returned a non-object response.")
        return payload


def _object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise OpenDesignProtocolError(f"OpenDesign returned an invalid {key} list.")
    return value
