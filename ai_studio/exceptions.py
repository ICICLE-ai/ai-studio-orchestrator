"""Custom exceptions for AI Studio services.

These exceptions carry HTTP-style status codes and structured detail payloads
so that consuming services (e.g. FastAPI apps) can translate them into
appropriate HTTP responses.
"""


class ServiceError(Exception):
    """Base exception for errors originating from external service calls."""

    def __init__(self, status_code: int, detail: dict) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail.get("message", str(detail)))


class AuthenticationError(ServiceError):
    """Raised when authentication against an external service fails."""


class UpstreamServiceError(ServiceError):
    """Raised when an upstream service returns an error response."""


class ServiceUnavailableError(ServiceError):
    """Raised when an upstream service cannot be reached."""


class InvalidResponseError(ServiceError):
    """Raised when an upstream service returns an unparseable response."""
