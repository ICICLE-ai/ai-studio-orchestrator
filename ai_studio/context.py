"""Request-scoped contextvars shared across modules."""

import contextvars

REQUEST_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="-",
)
