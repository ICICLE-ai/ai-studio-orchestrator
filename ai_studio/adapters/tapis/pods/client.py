"""Typed async client for creating and managing Tapis pods resources."""

import logging

import httpx

from ai_studio.adapters.http import make_request
from ai_studio.core import tapis_config
from ai_studio.exceptions import UpstreamServiceError
from ai_studio.adapters.tapis.pods.schemas import (
    CreateTapisPod,
    CreateTapisPodVolume,
    CreateTapisPodVolumeSnapshot,
    TapisPodApiResponse,
    TapisPodCredentialsApiResponse,
    TapisPodVolumeApiResponse,
    TapisPodVolumeSnapshotApiResponse,
)

logger = logging.getLogger("ai_studio.adapters.tapis.pods")


class TapisPodsClient:
    """Handles HTTP requests to the Tapis Pods API for managing pods, volumes, and snapshots."""

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        response_model,
        json_data: dict | None = None,
    ):
        """Send an HTTP request to the Tapis Pods API and validate the response."""
        return await make_request(
            client=client,
            method=method,
            url=url,
            json_data=json_data,
            headers={"X-Tapis-Token": tapis_config.admin_token.get_secret_value()},
            response_model=response_model,
            upstream_error_message="Tapis Pods API returned an error",
            invalid_response_message="Tapis Pods API returned invalid response format",
            unavailable_message="Unable to reach Tapis Pods service",
        )

    async def get_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        """Return a Tapis pod by ID."""
        return await self._make_request(
            client=client,
            method="GET",
            url=f"/v3/pods/{pod_id}",
            response_model=TapisPodApiResponse,
        )

    async def get_pod_credentials(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodCredentialsApiResponse:
        """Return Tapis-generated credentials for a template-backed pod."""
        return await self._make_request(
            client=client,
            method="GET",
            url=f"/v3/pods/{pod_id}/credentials",
            response_model=TapisPodCredentialsApiResponse,
        )

    async def get_volume(
        self, volume_id: str, client: httpx.AsyncClient
    ) -> TapisPodVolumeApiResponse:
        """Return a Tapis pod volume by ID."""
        return await self._make_request(
            client=client,
            method="GET",
            url=f"/v3/pods/volumes/{volume_id}",
            response_model=TapisPodVolumeApiResponse,
        )

    async def get_or_create_pod(
        self, pod_config: CreateTapisPod, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        """Return an existing pod or create it when Tapis reports 404."""
        try:
            existing = await self.get_pod(pod_config.pod_id, client)
            logger.info("pods.get_or_create.exists pod_id=%s", pod_config.pod_id)
            return existing
        except UpstreamServiceError as e:
            if e.status_code == 404:
                return await self.create_pod(pod_config, client)
            raise

    async def get_or_create_volume(
        self, volume_config: CreateTapisPodVolume, client: httpx.AsyncClient
    ) -> TapisPodVolumeApiResponse:
        """Return an existing volume or create it when Tapis reports 404."""
        try:
            existing = await self.get_volume(volume_config.volume_id, client)
            logger.info(
                "pods.get_or_create_volume.exists volume_id=%s",
                volume_config.volume_id,
            )
            return existing
        except UpstreamServiceError as e:
            if e.status_code == 404:
                return await self.create_volume(volume_config, client)
            raise

    async def create_pod(
        self, pod_config: CreateTapisPod, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        """Create a Tapis pod from a complete pod configuration."""
        logger.info("pods.create pod_id=%s", pod_config.pod_id)
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
        """Replace an existing Tapis pod configuration."""
        logger.info("pods.update pod_id=%s", pod_id)
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
        """Create a Tapis pod volume."""
        logger.info("pods.create_volume volume_id=%s", volume_config.volume_id)
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
        """Create a snapshot from an existing Tapis pod volume."""
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
        """Request that Tapis start a pod instance."""
        logger.info("pods.start pod_id=%s", pod_id)
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/pods/{pod_id}/start",
            response_model=TapisPodApiResponse,
        )

    async def stop_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        """Request that Tapis stop a pod instance."""
        logger.info("pods.stop pod_id=%s", pod_id)
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/pods/{pod_id}/stop",
            response_model=TapisPodApiResponse,
        )

    async def restart_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        """Request that Tapis restart a pod instance."""
        logger.info("pods.restart pod_id=%s", pod_id)
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/pods/{pod_id}/restart",
            response_model=TapisPodApiResponse,
        )

    async def delete_pod(
        self, pod_id: str, client: httpx.AsyncClient
    ) -> TapisPodApiResponse:
        """Delete a Tapis pod by ID."""
        logger.info("pods.delete pod_id=%s", pod_id)
        return await self._make_request(
            client=client,
            method="DELETE",
            url=f"/v3/pods/{pod_id}",
            response_model=TapisPodApiResponse,
        )

    async def delete_volume(
        self, volume_id: str, client: httpx.AsyncClient
    ) -> TapisPodVolumeApiResponse:
        """Delete a Tapis pod volume by ID."""
        logger.info("pods.delete_volume volume_id=%s", volume_id)
        return await self._make_request(
            client=client,
            method="DELETE",
            url=f"/v3/pods/volumes/{volume_id}",
            response_model=TapisPodVolumeApiResponse,
        )
