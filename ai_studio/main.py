"""FastAPI application entrypoint for AI Studio backend services."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx import AsyncClient

from ai_studio.api import api_router
from ai_studio.core.config import tapis_config

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage shared resources for the FastAPI application lifecycle.

    Args:
        app: FastAPI application instance.

    Yields:
        None. Control is yielded while the application is running.
    """
    app.state.client = AsyncClient(base_url=tapis_config.base_url)
    yield
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
app.include_router(api_router)


def main():
    """Run a lightweight local entrypoint for manual invocation.

    Returns:
        None.
    """
    print("Hello from ICICLE AI Studio!")


if __name__ == "__main__":
    main()
