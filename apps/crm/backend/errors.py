"""CRM application errors."""

from __future__ import annotations


class CrmError(Exception):
    """Base CRM app error."""

    code = "crm_error"
    status_code = 400

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ValidationError(CrmError):
    code = "validation_error"


class NotFoundError(CrmError):
    code = "not_found"
    status_code = 404


def error_payload(error: CrmError) -> dict[str, object]:
    return {"ok": False, "error": error.code, "message": str(error), "details": error.details}
