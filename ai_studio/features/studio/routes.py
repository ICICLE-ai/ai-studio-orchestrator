"""Route registration for studio lifecycle endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Security, status
from fastapi.security import APIKeyHeader
from httpx import AsyncClient
from pydantic import SecretStr

from ai_studio.api.dependencies import (
    get_client,
    get_garage_client,
    get_tapis_clients,
)
from ai_studio.adapters.tapis.auth import schemas as auth_schemas
from ai_studio.features.studio.schemas import StudioLifecycleResult, StudioResponse
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


@router.post(
    "/studio",
    summary="Provision studio",
    description="Provision the AI Studio resources for the authenticated user.",
    response_description="Provisioned studio response envelope.",
)
async def create_studio(
    token: Annotated[
        str, Security(APIKeyHeader(name="X-Tapis-Token", auto_error=True))
    ],
    service: Annotated[StudioService, Depends(get_studio_service)],
) -> StudioResponse[auth_schemas.TapisUserInfo]:
    user = await service.provision_studio(SecretStr(token))
    return StudioResponse(
        status=status.HTTP_200_OK,
        version=1,
        message="Studio provisioned",
        result=user,
    )


@router.patch(
    "/studio/start",
    summary="Start studio",
    description="Start the provisioned AI Studio resources for the authenticated user.",
    response_description="Studio lifecycle response envelope.",
)
async def start_studio(
    token: Annotated[
        str, Security(APIKeyHeader(name="X-Tapis-Token", auto_error=True))
    ],
    service: Annotated[StudioService, Depends(get_studio_service)],
) -> StudioResponse[StudioLifecycleResult]:
    result = await service.start_studio(SecretStr(token))
    return StudioResponse(
        status=status.HTTP_200_OK,
        version=1,
        message="Studio started",
        result=result,
    )


@router.patch(
    "/studio/stop",
    summary="Stop studio",
    description="Stop the running AI Studio resources for the authenticated user.",
    response_description="Studio lifecycle response envelope.",
)
async def stop_studio(
    token: Annotated[
        str, Security(APIKeyHeader(name="X-Tapis-Token", auto_error=True))
    ],
    service: Annotated[StudioService, Depends(get_studio_service)],
) -> StudioResponse[StudioLifecycleResult]:
    result = await service.stop_studio(SecretStr(token))
    return StudioResponse(
        status=status.HTTP_200_OK,
        version=1,
        message="Studio stopped",
        result=result,
    )


@router.delete(
    "/studio",
    summary="Delete studio",
    description="Delete the provisioned AI Studio resources for the authenticated user.",
    response_description="Studio lifecycle response envelope.",
)
async def delete_studio(
    token: Annotated[
        str, Security(APIKeyHeader(name="X-Tapis-Token", auto_error=True))
    ],
    service: Annotated[StudioService, Depends(get_studio_service)],
) -> StudioResponse[StudioLifecycleResult]:
    result = await service.delete_studio(SecretStr(token))
    return StudioResponse(
        status=status.HTTP_200_OK,
        version=1,
        message="Studio deleted",
        result=result,
    )
