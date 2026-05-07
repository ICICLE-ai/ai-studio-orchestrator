"""Custom exceptions for AI Studio services.

These exceptions carry HTTP-style status codes and structured detail payloads
so that consuming services (e.g. FastAPI apps) can translate them into
appropriate HTTP responses.
"""

_UPSTREAM_DETAIL_LIMIT = 512


def _truncate_details(detail: dict) -> dict:
    """Cap the ``details`` field so upstream payloads can't flood logs or responses."""
    value = detail.get("details")
    if isinstance(value, str) and len(value) > _UPSTREAM_DETAIL_LIMIT:
        detail = {**detail, "details": value[:_UPSTREAM_DETAIL_LIMIT] + "... [truncated]"}
    return detail


class ServiceError(Exception):
    """Base exception for errors originating from external service calls."""

    def __init__(self, status_code: int, detail: dict) -> None:
        """Store an HTTP-style status code and structured error detail."""
        detail = _truncate_details(detail)
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


class GarageKeyConflictError(ServiceError):
    """Raised when a Garage key exists but its recoverable secret is missing."""
