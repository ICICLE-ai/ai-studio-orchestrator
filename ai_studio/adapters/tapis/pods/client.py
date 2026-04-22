"""Typed async client for creating and managing Tapis pods resources."""

import httpx
from pydantic import BaseModel, ValidationError

from ai_studio.core import tapis_config
from ai_studio.exceptions import (
    InvalidResponseError,
    ServiceUnavailableError,
    UpstreamServiceError,
)
from ai_studio.adapters.tapis.pods.schemas import (
    CreateTapisPod,
    CreateTapisPodVolume,
    CreateTapisPodVolumeSnapshot,
    TapisPodApiResponse,
    TapisPodCredentialsApiResponse,
    TapisPodVolumeApiResponse,
    TapisPodVolumeSnapshotApiResponse,
)


class TapisPodsClient:
    """Handles HTTP requests to the Tapis Pods API for managing pods, volumes, and snapshots."""

    async def _make_request[T: BaseModel](
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        response_model: type[T],
        json_data: dict | None = None,
    ) -> T:
        """Send an HTTP request to the Tapis Pods API and validate the response."""
        try:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
                headers={"X-Tapis-Token": tapis_config.admin_token},
            )
            if response.status_code not in (200, 201):
                raise UpstreamServiceError(
                    status_code=response.status_code,
                    detail={
                        "message": "Tapis Pods API returned an error",
                        "details": response.text,
                    },
                )
            return response_model.model_validate(response.json())
        except httpx.RequestError as error:
            raise ServiceUnavailableError(
                status_code=503,
                detail={
                    "message": "Unable to reach Tapis Pods service",
                    "details": f"{type(error).__name__}: {str(error)}",
                },
            )
        except ValidationError as error:
            errors = error.errors()
            error_details = [f"{err['loc'][-1]}: {err['msg']}" for err in errors]
            raise InvalidResponseError(
                status_code=502,
                detail={
                    "message": "Tapis Pods API returned invalid response format",
                    "details": error_details,
                },
            )

    async def get_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        return await self._make_request(
            client=client,
            method="GET",
            url=f"/v3/pods/{pod_id}",
            response_model=TapisPodApiResponse,
        )

    async def get_pod_credentials(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodCredentialsApiResponse:
        return await self._make_request(
            client=client,
            method="GET",
            url=f"/v3/pods/{pod_id}/credentials",
            response_model=TapisPodCredentialsApiResponse,
        )

    async def get_volume(
        self, volume_id: str, client: httpx.AsyncClient
    ) -> TapisPodVolumeApiResponse:
        return await self._make_request(
            client=client,
            method="GET",
            url=f"/v3/pods/volumes/{volume_id}",
            response_model=TapisPodVolumeApiResponse,
        )

    async def get_or_create_pod(
        self, pod_config: CreateTapisPod, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        try:
            return await self.get_pod(pod_config.pod_id, client)
        except UpstreamServiceError as e:
            if e.status_code == 404:
                return await self.create_pod(pod_config, client)
            raise

    async def get_or_create_volume(
        self, volume_config: CreateTapisPodVolume, client: httpx.AsyncClient
    ) -> TapisPodVolumeApiResponse:
        try:
            return await self.get_volume(volume_config.volume_id, client)
        except UpstreamServiceError as e:
            if e.status_code == 404:
                return await self.create_volume(volume_config, client)
            raise

    async def create_pod(
        self, pod_config: CreateTapisPod, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v3/pods",
            json_data=pod_config.model_dump(),
            response_model=TapisPodApiResponse,
        )

    async def update_pod(
        self, pod_id: str, pod_config: CreateTapisPod, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        return await self._make_request(
            client=client,
            method="PUT",
            url=f"/v3/pods/{pod_id}",
            json_data=pod_config.model_dump(),
            response_model=TapisPodApiResponse,
        )

    async def create_volume(
        self, volume_config: CreateTapisPodVolume, client: httpx.AsyncClient
    ) -> TapisPodVolumeApiResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v3/pods/volumes",
            json_data=volume_config.model_dump(),
            response_model=TapisPodVolumeApiResponse,
        )

    async def create_volume_snapshot(
        self, snapshot_config: CreateTapisPodVolumeSnapshot, client: httpx.AsyncClient
    ) -> TapisPodVolumeSnapshotApiResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v3/pods/snapshots",
            json_data=snapshot_config.model_dump(),
            response_model=TapisPodVolumeSnapshotApiResponse,
        )

    async def start_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/pods/{pod_id}/start",
            response_model=TapisPodApiResponse,
        )

    async def stop_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/pods/{pod_id}/stop",
            response_model=TapisPodApiResponse,
        )

    async def restart_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/pods/{pod_id}/restart",
            response_model=TapisPodApiResponse,
        )

    async def delete_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        return await self._make_request(
            client=client,
            method="DELETE",
            url=f"/v3/pods/{pod_id}",
            response_model=TapisPodApiResponse,
        )
