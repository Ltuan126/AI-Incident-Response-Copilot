"""Errors that connectors expose to the investigation worker."""


class ConnectorError(Exception):
    """A source query failed in a way the worker can record and continue past."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
