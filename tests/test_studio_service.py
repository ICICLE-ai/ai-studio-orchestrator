"""Tests for studio lifecycle orchestration behavior."""

import asyncio
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
from ai_studio.exceptions import InvalidResponseError, UpstreamServiceError
from ai_studio.features.studio.service import (
    StudioService,
    TapisClients,
    _resource_id_for_username,
)


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
        old_tenant = tapis_config.tenant
        try:
            tapis_config.traefik_public_host = "aistudio.pods.icicleai.tapis.io"
            tapis_config.tenant = "testtenant"
            rendered = StudioService._render_traefik_route_file("alice")
        finally:
            tapis_config.traefik_public_host = old_host
            tapis_config.tenant = old_tenant

        self.assertIn("Host(`aistudio.pods.icicleai.tapis.io`)", rendered)
        self.assertIn("PathPrefix(`/u/alice/datasets`)", rendered)
        self.assertIn("PathPrefix(`/u/alice/mlflow`)", rendered)
        self.assertIn("datasets-buffer", rendered)
        self.assertIn(
            "http://pods-tacc-testtenant-aliceaistudiodatasets:8000", rendered
        )
        self.assertIn(
            "http://pods-tacc-testtenant-aliceaistudiomlflow:5000", rendered
        )

    def test_resource_id_preserves_tacc_usernames_and_slugifies_email(self):
        self.assertEqual(_resource_id_for_username("alice"), "alice")
        email_resource_id = _resource_id_for_username("user@gmail.com")

        self.assertRegex(email_resource_id, r"^usergmailcom[a-f0-9]{8}$")
        self.assertNotIn("@", email_resource_id)
        self.assertNotIn("-", email_resource_id)
        self.assertEqual(email_resource_id, _resource_id_for_username("User@Gmail.com"))

    def test_write_route_file_slugifies_email_username(self):
        service, _, _ = self._make_service()
        resource_id = _resource_id_for_username("user@gmail.com")

        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = tapis_config.traefik_dynamic_dir
            tapis_config.traefik_dynamic_dir = Path(tmpdir)
            try:
                service._write_traefik_route_file("user@gmail.com")
                route_file = Path(tmpdir) / f"{resource_id}.yml"
                self.assertTrue(route_file.exists())
                self.assertIn(f"/u/{resource_id}/datasets", route_file.read_text())
            finally:
                tapis_config.traefik_dynamic_dir = old_dir

    def test_write_route_file_replaces_file_and_cleans_temp(self):
        service, _, _ = self._make_service()

        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = tapis_config.traefik_dynamic_dir
            tapis_config.traefik_dynamic_dir = Path(tmpdir)
            route_file = Path(tmpdir) / "alice.yml"
            route_file.write_text("stale route")
            try:
                service._write_traefik_route_file("alice")
                self.assertIn("/u/alice/datasets", route_file.read_text())
                self.assertEqual(
                    [path for path in Path(tmpdir).iterdir() if path.suffix == ".tmp"],
                    [],
                )
            finally:
                tapis_config.traefik_dynamic_dir = old_dir

    async def test_start_studio_uses_resource_id_for_email_user_resources(self):
        service, tapis, _ = self._make_service()
        tapis.auth.validate_token.return_value = auth_schemas.TapisUserInfo(
            username="user@gmail.com"
        )
        tapis.pods.start_pod = AsyncMock()
        resource_id = _resource_id_for_username("user@gmail.com")

        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = tapis_config.traefik_dynamic_dir
            tapis_config.traefik_dynamic_dir = Path(tmpdir)
            try:
                result = await service.start_studio(SecretStr("user-token"))
            finally:
                tapis_config.traefik_dynamic_dir = old_dir

        self.assertEqual(result.username, "user@gmail.com")
        self.assertEqual(
            result.changed,
            [
                f"{resource_id}aistudiodb",
                f"{resource_id}aistudiogarage",
                f"{resource_id}aistudiomlflow",
                f"{resource_id}aistudiodatasets",
            ],
        )

    async def test_upsert_datasets_pod_keeps_real_username_for_tapis_auth(self):
        service, tapis, _ = self._make_service()
        resource_id = _resource_id_for_username("user@gmail.com")
        tapis.pods.get_pod = AsyncMock(
            side_effect=UpstreamServiceError(status_code=404, detail={"message": "nope"})
        )
        tapis.pods.create_pod = AsyncMock()

        await service._upsert_datasets_pod(
            resource_id=resource_id,
            allowed_username="user@gmail.com",
            db_pod_id=f"{resource_id}aistudiodb",
            db_internal_host=f"pods-tacc-testtenant-{resource_id}aistudiodb",
            db_username="db-user",
            db_password=SecretStr("db-pass"),
            garage_internal_host=f"pods-tacc-testtenant-{resource_id}aistudiogarage",
            datasets_credentials={
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
                "bucket_id": "datasets",
            },
        )

        pod_config = tapis.pods.create_pod.call_args.args[0]
        self.assertEqual(pod_config.pod_id, f"{resource_id}aistudiodatasets")
        self.assertEqual(
            pod_config.networking["default"].tapis_auth_allowed_users,
            ["user@gmail.com"],
        )

    async def test_malformed_garage_admin_secret_has_clear_error(self):
        service, tapis, _ = self._make_service()
        tapis.vault.read_secret.return_value.result.secretMap = {
            "rpc_secret": "rpc",
            "admin_token": "admin",
        }

        with self.assertRaises(InvalidResponseError) as ctx:
            await service._ensure_garage_admin_secret(
                token=SecretStr("user-token"),
                username="alice",
            )

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("metrics_token", ctx.exception.detail["details"])
        self.assertIn("delete or repair", ctx.exception.detail["details"])

    async def test_lifecycle_lock_serializes_same_user_actions(self):
        locks = {}
        service, tapis, _ = self._make_service()
        service._lifecycle_locks = locks
        tapis.auth.validate_token.return_value = auth_schemas.TapisUserInfo(
            username="user@gmail.com"
        )
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def start_pod(pod_id, client):
            calls.append(pod_id)
            if len(calls) == 1:
                started.set()
                await release.wait()

        tapis.pods.start_pod = AsyncMock(side_effect=start_pod)

        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = tapis_config.traefik_dynamic_dir
            tapis_config.traefik_dynamic_dir = Path(tmpdir)
            try:
                first = asyncio.create_task(service.start_studio(SecretStr("token")))
                await started.wait()
                second = asyncio.create_task(service.start_studio(SecretStr("token")))
                await asyncio.sleep(0)
                self.assertEqual(len(calls), 1)
                release.set()
                await asyncio.gather(first, second)
            finally:
                tapis_config.traefik_dynamic_dir = old_dir

        self.assertEqual(len(calls), 8)
