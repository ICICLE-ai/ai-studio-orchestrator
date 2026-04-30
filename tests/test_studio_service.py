"""Tests for studio lifecycle orchestration behavior."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock

from pydantic import SecretStr, ValidationError

os.environ.setdefault("TAPIS_ADMIN_TOKEN", "admin-token")
os.environ.setdefault("TAPIS_BASE_URL", "https://tapis.test")
os.environ.setdefault("TAPIS_TENANT", "testtenant")

from ai_studio.adapters.tapis.auth import schemas as auth_schemas
from ai_studio.core import tapis_config
from ai_studio.exceptions import InvalidResponseError, UpstreamServiceError
from ai_studio.features.studio.schemas import (
    StudioLifecycleOptions,
    StudioPodResourceOptions,
    StudioProvisionRequest,
    StudioResourceSetOptions,
    StudioVolumeOptions,
    StudioVolumeSetOptions,
    get_studio_provision_options,
    resolve_studio_provision_config,
)
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
        service = StudioService(tapis=tapis, garage=garage, http_client=AsyncMock())
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
            "http://pods-tacc-testtenant-aliceaistudiodatasets:5000", rendered
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

    def test_resolve_provision_config_uses_standard_defaults(self):
        config = resolve_studio_provision_config()

        self.assertEqual(config.profile, "standard")
        self.assertEqual(config.volumes.garage.size_limit, 1024)
        self.assertEqual(config.volumes.postgres.size_limit, 1024)
        self.assertEqual(config.resources.mlflow.cpu_limit, 2000)
        self.assertEqual(config.lifecycle.time_to_stop_default, 43200)

    def test_resolve_provision_config_merges_custom_request(self):
        config = resolve_studio_provision_config(
            StudioProvisionRequest(
                profile="custom",
                volumes=StudioVolumeSetOptions(
                    garage=StudioVolumeOptions(size_limit=2048),
                ),
                resources=StudioResourceSetOptions(
                    mlflow=StudioPodResourceOptions(
                        cpu_request=500,
                        cpu_limit=4000,
                        mem_request=1024,
                        mem_limit=8192,
                    ),
                ),
                lifecycle=StudioLifecycleOptions(time_to_stop_default=86400),
            )
        )

        self.assertEqual(config.profile, "custom")
        self.assertEqual(config.volumes.garage.size_limit, 2048)
        self.assertEqual(config.volumes.postgres.size_limit, 1024)
        self.assertEqual(config.resources.mlflow.cpu_limit, 4000)
        self.assertEqual(config.resources.datasets.cpu_limit, 2000)
        self.assertEqual(config.lifecycle.time_to_stop_default, 86400)

    def test_get_studio_provision_options_exposes_profiles_and_constraints(self):
        options = get_studio_provision_options()

        self.assertEqual(
            [profile.id for profile in options.profiles],
            ["small", "standard", "large"],
        )
        self.assertIn(1024, options.constraints.volume_size_limit_values)
        self.assertEqual(options.constraints.memory_unit, "MiB")

    def test_volume_options_rejects_non_power_of_two_size(self):
        with self.assertRaises(ValidationError):
            StudioVolumeOptions(size_limit=300)

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

    async def test_upsert_datasets_pod_uses_default_tapis_networking(self):
        service, tapis, _ = self._make_service()
        resource_id = _resource_id_for_username("user@gmail.com")
        tapis.pods.get_pod = AsyncMock(
            side_effect=UpstreamServiceError(status_code=404, detail={"message": "nope"})
        )
        tapis.pods.create_pod = AsyncMock()

        await service._upsert_datasets_pod(
            resource_id=resource_id,
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
            resources=StudioPodResourceOptions(),
            time_to_stop_default=43200,
        )

        pod_config = tapis.pods.create_pod.call_args.args[0]
        self.assertEqual(pod_config.pod_id, f"{resource_id}aistudiodatasets")
        self.assertEqual(pod_config.networking["default"].port, 5000)
        self.assertFalse(pod_config.networking["default"].tapis_auth)

    async def test_upsert_datasets_pod_applies_requested_resources_and_lifecycle(self):
        service, tapis, _ = self._make_service()
        tapis.pods.get_pod = AsyncMock(
            side_effect=UpstreamServiceError(status_code=404, detail={"message": "nope"})
        )
        tapis.pods.create_pod = AsyncMock()

        await service._upsert_datasets_pod(
            resource_id="alice",
            db_pod_id="aliceaistudiodb",
            db_internal_host="pods-tacc-testtenant-aliceaistudiodb",
            db_username="db-user",
            db_password=SecretStr("db-pass"),
            garage_internal_host="pods-tacc-testtenant-aliceaistudiogarage",
            datasets_credentials={
                "access_key_id": "access-key",
                "secret_access_key": "secret-key",
                "bucket_id": "datasets",
            },
            resources=StudioPodResourceOptions(
                cpu_request=500,
                cpu_limit=4000,
                mem_request=1024,
                mem_limit=8192,
                gpus=1,
            ),
            time_to_stop_default=86400,
        )

        pod_config = tapis.pods.create_pod.call_args.args[0]
        self.assertEqual(pod_config.time_to_stop_default, 86400)
        self.assertEqual(pod_config.resources.cpu_request, 500)
        self.assertEqual(pod_config.resources.cpu_limit, 4000)
        self.assertEqual(pod_config.resources.mem_request, 1024)
        self.assertEqual(pod_config.resources.mem_limit, 8192)
        self.assertEqual(pod_config.resources.gpus, 1)

    async def test_create_volume_raises_conflict_for_existing_size_mismatch(self):
        service, tapis, _ = self._make_service()
        volume = SimpleNamespace(
            result=SimpleNamespace(volume_id="aliceaistudiodb", size_limit=1024)
        )
        tapis.pods.get_or_create_volume.return_value = volume

        with self.assertRaises(UpstreamServiceError) as ctx:
            await service._create_volume(
                volume_id="aliceaistudiodb",
                description="Database volume",
                size_limit=2048,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("already exists", ctx.exception.detail["details"])

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
