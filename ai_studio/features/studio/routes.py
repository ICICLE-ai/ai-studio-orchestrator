"""Route registration for studio lifecycle endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Security, status
from fastapi.security import APIKeyHeader
from httpx import AsyncClient

from ai_studio.api.dependencies import (
    get_client,
    get_garage_client,
    get_tapis_clients,
)
from ai_studio.features.studio.schemas import StudioResponse
from ai_studio.features.studio.service import StudioService, TapisClients

router = APIRouter(prefix="/api")


def get_studio_service(
    tapis: Annotated[TapisClients, Depends(get_tapis_clients)],
    garage=Depends(get_garage_client),
    client: AsyncClient = Depends(get_client),
) -> StudioService:
    return StudioService(
        tapis=tapis,
        garage=garage,
        tapis_client=client,
    )


@router.post("/studio")
async def create_studio(
    token: Annotated[
        str, Security(APIKeyHeader(name="X-Tapis-Token", auto_error=True))
    ],
    service: Annotated[StudioService, Depends(get_studio_service)],
) -> StudioResponse:
    user = await service.provision_studio(token)
    return StudioResponse(
        status=status.HTTP_200_OK,
        version=1,
        message="Studio provisioned",
        result=user,
    )


@router.patch("/studio/start")
async def start_studio():
    """Start previously provisioned studio services."""
    pass


@router.patch("/studio/stop")
async def stop_studio():
    """Stop running studio services for the current user."""
    pass


@router.delete("/studio")
async def delete_studio():
    """Delete all studio resources associated with the current user."""
    pass
