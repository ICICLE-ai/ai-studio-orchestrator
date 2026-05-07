"""Route registration for studio lifecycle endpoints."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Security, status
from fastapi.security import APIKeyHeader
from httpx import AsyncClient
from pydantic import SecretStr

from ai_studio_orchestrator.shared.dependencies import (
    get_client,
    get_garage_client,
    get_lifecycle_locks,
    get_tapis_clients,
)
from ai_studio_orchestrator.adapters.tapis.auth import schemas as auth_schemas
from ai_studio_orchestrator.features.studio.schemas import (
    StudioLifecycleResult,
    StudioProvisionOptionsResponse,
    StudioProvisionRequest,
    StudioResponse,
    get_studio_provision_options,
)
from ai_studio_orchestrator.features.studio.service import StudioService, TapisClients

router = APIRouter(prefix="/api")


def get_studio_service(
    tapis: Annotated[TapisClients, Depends(get_tapis_clients)],
    garage=Depends(get_garage_client),
    http_client: AsyncClient = Depends(get_client),
    lifecycle_locks: dict[str, asyncio.Lock] = Depends(get_lifecycle_locks),
) -> StudioService:
    """Build the request-scoped studio orchestration service."""
    # Keep the adapters and shared transport separate: ``tapis`` owns API
    # semantics, while ``http_client`` owns connection pooling and timeouts.
    return StudioService(
        tapis=tapis,
        garage=garage,
        http_client=http_client,
        lifecycle_locks=lifecycle_locks,
    )


@router.get(
    "/studio/options",
    summary="List studio provisioning options",
    description="Return frontend-safe provisioning profiles and constraints.",
    response_description="Studio provisioning options.",
)
async def get_studio_options() -> StudioResponse[StudioProvisionOptionsResponse]:
    """Return provisioning profiles and constraints for frontend controls."""
    return StudioResponse(
        status=status.HTTP_200_OK,
        version=1,
        message="Studio provisioning options",
        result=get_studio_provision_options(),
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
    provision: StudioProvisionRequest | None = None,
) -> StudioResponse[auth_schemas.TapisUserInfo]:
    """Provision all per-user studio resources for the authenticated caller."""
    user = await service.provision_studio(SecretStr(token), provision)
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
    """Start provisioned studio pods for the authenticated caller."""
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
    """Stop running studio pods for the authenticated caller."""
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
    """Delete studio pods, volumes, and routing for the authenticated caller."""
    result = await service.delete_studio(SecretStr(token))
    return StudioResponse(
        status=status.HTTP_200_OK,
        version=1,
        message="Studio deleted",
        result=result,
    )
