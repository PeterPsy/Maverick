"""Redaction-safe laboratory boundary failures."""


class LabAuthorizationError(ValueError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)
