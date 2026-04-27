"""Tests for studio lifecycle orchestration behavior."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from pydantic import SecretStr

os.environ.setdefault("TAPIS_ADMIN_TOKEN", "admin-token")
os.environ.setdefault("TAPIS_BASE_URL", "https://tapis.test")
os.environ.setdefault("TAPIS_TENANT", "testtenant")

from ai_studio.adapters.tapis.auth import schemas as auth_schemas
from ai_studio.core import tapis_config
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

        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = tapis_config.traefik_dynamic_dir
            tapis_config.traefik_dynamic_dir = Path(tmpdir)
            try:
                result = await service.start_studio(SecretStr("user-token"))
                route_file = Path(tmpdir) / "alice.yml"
                self.assertTrue(route_file.exists())
                self.assertIn("/u/alice/datasets", route_file.read_text())
                self.assertIn("/u/alice/mlflow", route_file.read_text())
            finally:
                tapis_config.traefik_dynamic_dir = old_dir

        self.assertEqual(
            result.changed,
            [
                "aliceaistudiodb",
                "aliceaistudiogarage",
                "aliceaistudiomlflow",
                "aliceaistudiodatasets",
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
                "aliceaistudiodatasets",
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
            if pod_id == "aliceaistudiodatasets":
                raise UpstreamServiceError(status_code=404, detail={"message": "missing"})

        async def delete_volume(volume_id, client):
            if volume_id == "aliceaistudiodb":
                raise UpstreamServiceError(status_code=404, detail={"message": "missing"})

        tapis.pods.delete_pod = AsyncMock(side_effect=delete_pod)
        tapis.pods.delete_volume = AsyncMock(side_effect=delete_volume)

        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = tapis_config.traefik_dynamic_dir
            tapis_config.traefik_dynamic_dir = Path(tmpdir)
            route_file = Path(tmpdir) / "alice.yml"
            route_file.write_text("stale route")
            try:
                result = await service.delete_studio(SecretStr("user-token"))
                self.assertFalse(route_file.exists())
            finally:
                tapis_config.traefik_dynamic_dir = old_dir

        self.assertIn("aliceaistudiodb", result.skipped)
        self.assertIn("aliceaistudiodatasets", result.skipped)
        self.assertIn("aliceaistudiogarage", result.changed)
        self.assertIn("aliceaistudiomlflowpipcache", result.changed)

    def test_render_traefik_route_file_uses_expected_paths(self):
        old_host = tapis_config.traefik_public_host
        try:
            tapis_config.traefik_public_host = "aistudio.pods.icicleai.tapis.io"
            rendered = StudioService._render_traefik_route_file("alice")
        finally:
            tapis_config.traefik_public_host = old_host

        self.assertIn("Host(`aistudio.pods.icicleai.tapis.io`)", rendered)
        self.assertIn("PathPrefix(`/u/alice/datasets`)", rendered)
        self.assertIn("PathPrefix(`/u/alice/mlflow`)", rendered)
        self.assertIn(
            "http://pods-tacc-testtenant-aliceaistudiodatasets:8000", rendered
        )
        self.assertIn(
            "http://pods-tacc-testtenant-aliceaistudiomlflow:5000", rendered
        )
