"""Bounded public errors; never include a filesystem path or raw exception."""


class AppError(ValueError):
    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)
