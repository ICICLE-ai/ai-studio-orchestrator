"""Tests for studio lifecycle orchestration behavior."""

import os
import unittest
from unittest.mock import AsyncMock

from pydantic import SecretStr

os.environ.setdefault("TAPIS_ADMIN_TOKEN", "admin-token")
os.environ.setdefault("TAPIS_BASE_URL", "https://tapis.test")
os.environ.setdefault("TAPIS_TENANT", "testtenant")

from ai_studio.adapters.tapis.auth import schemas as auth_schemas
from ai_studio.exceptions import UpstreamServiceError
from ai_studio.features.studio.service import StudioService, TapisClients


class StudioServiceLifecycleTest(unittest.IsolatedAsyncioTestCase):
    def _make_service(self) -> tuple[StudioService, object, object]:
        tapis = TapisClients(
            auth=AsyncMock(),
            pods=AsyncMock(),
            vault=AsyncMock(),
        )
        garage = AsyncMock()
        service = StudioService(tapis=tapis, garage=garage, tapis_client=AsyncMock())
        return service, tapis, garage

    async def test_start_studio_starts_pods_in_dependency_order(self):
        service, tapis, _ = self._make_service()
        tapis.auth.validate_token.return_value = auth_schemas.TapisUserInfo(
            username="alice"
        )
        tapis.pods.start_pod = AsyncMock()

        result = await service.start_studio(SecretStr("user-token"))

        self.assertEqual(
            result.changed,
            [
                "aliceaistudiodb",
                "aliceaistudiogarage",
                "aliceaistudiomlflow",
                "aliceaistudioprometheus",
                "aliceaistudiografana",
            ],
        )
        self.assertEqual(result.skipped, [])

    async def test_stop_studio_stops_pods_in_reverse_order(self):
        service, tapis, _ = self._make_service()
        tapis.auth.validate_token.return_value = auth_schemas.TapisUserInfo(
            username="alice"
        )
        tapis.pods.stop_pod = AsyncMock()

        result = await service.stop_studio(SecretStr("user-token"))

        self.assertEqual(
            result.changed,
            [
                "aliceaistudiografana",
                "aliceaistudioprometheus",
                "aliceaistudiomlflow",
                "aliceaistudiogarage",
                "aliceaistudiodb",
            ],
        )
        self.assertEqual(result.skipped, [])

    async def test_delete_studio_skips_missing_resources_and_deletes_volumes(self):
        service, tapis, _ = self._make_service()
        tapis.auth.validate_token.return_value = auth_schemas.TapisUserInfo(
            username="alice"
        )

        async def delete_pod(pod_id, client):
            if pod_id == "aliceaistudiografana":
                raise UpstreamServiceError(status_code=404, detail={"message": "missing"})

        async def delete_volume(volume_id, client):
            if volume_id == "aliceaistudiodb":
                raise UpstreamServiceError(status_code=404, detail={"message": "missing"})

        tapis.pods.delete_pod = AsyncMock(side_effect=delete_pod)
        tapis.pods.delete_volume = AsyncMock(side_effect=delete_volume)

        result = await service.delete_studio(SecretStr("user-token"))

        self.assertIn("aliceaistudiodb", result.skipped)
        self.assertIn("aliceaistudiografana", result.skipped)
        self.assertIn("aliceaistudiogarage", result.changed)
        self.assertIn("aliceaistudiomlflowpipcache", result.changed)
