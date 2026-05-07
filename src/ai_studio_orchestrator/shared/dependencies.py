"""FastAPI dependency providers used by AI Studio routes."""

import asyncio

import httpx
from fastapi import Request

from ai_studio_orchestrator.adapters.garage import GarageClient
from ai_studio_orchestrator.adapters.tapis.auth import TapisAuthClient
from ai_studio_orchestrator.adapters.tapis.pods import TapisPodsClient
from ai_studio_orchestrator.adapters.tapis.vaults import TapisVaultClient
from ai_studio_orchestrator.features.studio.service import TapisClients


def get_client(request: Request) -> httpx.AsyncClient:
    """Return the shared HTTP client stored on FastAPI application state."""
    return request.app.state.client


def get_lifecycle_locks(request: Request) -> dict[str, asyncio.Lock]:
    """Return shared per-resource lifecycle locks stored on app state."""
    return request.app.state.lifecycle_locks


def get_tapis_clients() -> TapisClients:
    """Build the typed Tapis adapter bundle for a request."""
    return TapisClients(
        auth=TapisAuthClient(),
        pods=TapisPodsClient(),
        vault=TapisVaultClient(),
    )


def get_garage_client() -> GarageClient:
    """Build the Garage adapter used by studio provisioning."""
    return GarageClient()
