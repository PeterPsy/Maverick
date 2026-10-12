"""Redaction-safe installation failures."""


class InstallationError(ValueError):
    def __init__(self, code: str, *, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)
