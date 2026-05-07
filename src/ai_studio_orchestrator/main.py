"""FastAPI application entrypoint for AI Studio backend services."""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ai_studio_orchestrator.context import REQUEST_ID_VAR
from ai_studio_orchestrator.core.config import tapis_config
from ai_studio_orchestrator.exceptions import ServiceError
from ai_studio_orchestrator.features.studio.routes import router as studio_router
from ai_studio_orchestrator.logger import configure_logger

configure_logger()
logger = logging.getLogger("ai_studio_orchestrator.main")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _sanitize_request_id(raw: str | None) -> str:
    """Accept the client-supplied X-Request-ID only if it matches a strict allowlist.

    Prevents log injection (CWE-117): the header is otherwise attacker-controlled
    and would otherwise be written verbatim into stdout, where embedded newlines
    or ANSI escapes could forge log lines or spoof structure.
    """
    if raw and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a sanitized request id to logs and response headers."""

    async def dispatch(self, request: Request, call_next):
        """Set request context, log timing, and add X-Request-ID to the response."""
        request_id = _sanitize_request_id(request.headers.get("X-Request-ID"))
        token = REQUEST_ID_VAR.set(request_id)
        start = time.perf_counter()
        logger.info(
            "request.start method=%s path=%s",
            request.method,
            request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "request.error method=%s path=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        finally:
            REQUEST_ID_VAR.reset(token)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request.end method=%s path=%s status=%d duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage shared resources for the FastAPI application lifecycle.

    Args:
        app: FastAPI application instance.

    Yields:
        None. Control is yielded while the application is running.
    """
    logger.info("lifespan.startup base_url=%s", tapis_config.base_url)
    app.state.client = httpx.AsyncClient(
        base_url=tapis_config.base_url,
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
    )
    # Shared by request-scoped StudioService instances to serialize mutations for
    # the same per-user studio resource within this orchestrator process.
    lifecycle_locks: dict[str, asyncio.Lock] = {}
    app.state.lifecycle_locks = lifecycle_locks
    try:
        yield
    finally:
        logger.info("lifespan.shutdown")
        await app.state.client.aclose()


app = FastAPI(
    title="AI Studio Orchestrator",
    summary="Provisioning and lifecycle API for AI Studio resources.",
    description=(
        "The AI Studio Orchestrator provisions, starts, stops, and deletes "
        "user studio resources and supporting infrastructure."
    ),
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(RequestIDMiddleware)
app.include_router(studio_router)


@app.exception_handler(ServiceError)
async def service_error_handler(
    request: Request,
    error: ServiceError,
) -> JSONResponse:
    """Translate structured service errors into JSON HTTP responses."""
    logger.warning(
        "request.service_error method=%s path=%s status=%d error=%s",
        request.method,
        request.url.path,
        error.status_code,
        type(error).__name__,
    )
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail})


@app.get("/health", include_in_schema=False)
async def health():
    """Return a minimal readiness response for load balancers."""
    return {"status": "ok"}


def main():
    """Run a lightweight local entrypoint for manual invocation.

    Returns:
        None.
    """
    print("Hello from ICICLE AI Studio!")


if __name__ == "__main__":
    main()
