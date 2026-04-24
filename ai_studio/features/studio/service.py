"""Studio orchestration use cases."""

from dataclasses import dataclass
import secrets
from typing import Literal

from httpx import AsyncClient
from pydantic import SecretStr

from ai_studio.adapters.garage import GarageClient
from ai_studio.adapters.tapis.auth import TapisAuthClient
from ai_studio.adapters.tapis.auth import schemas as auth_schemas
from ai_studio.adapters.tapis.pods import TapisPodsClient
from ai_studio.adapters.tapis.pods import schemas as pods_schemas
from ai_studio.adapters.tapis.vaults import TapisVaultClient
from ai_studio.adapters.tapis.vaults import schemas as vault_schemas
from ai_studio.core import tapis_config
from ai_studio.exceptions import UpstreamServiceError
from ai_studio.features.studio.schemas import StudioLifecycleResult

GARAGE_ADMIN_SECRET_ID = "aistudio-garage-admin"
GARAGE_ARTIFACTS_SECRET_ID = "aistudio-garage-artifacts"
GARAGE_DATASETS_SECRET_ID = "aistudio-garage-datasets"


@dataclass(frozen=True)
class TapisClients:
    """External Tapis clients used by the studio orchestration service."""

    auth: TapisAuthClient
    pods: TapisPodsClient
    vault: TapisVaultClient


class StudioService:
    """Coordinate all resources needed for a user's AI Studio environment."""

    def __init__(
        self,
        tapis: TapisClients,
        garage: GarageClient,
        tapis_client: AsyncClient,
    ):
        self._tapis = tapis
        self._garage = garage
        self._tapis_client = tapis_client

    async def provision_studio(self, token: SecretStr) -> auth_schemas.TapisUserInfo:
        """Provision initial AI Studio resources for the authenticated user."""

        user = await self._tapis.auth.validate_token(token, self._tapis_client)
        rpc_secret, admin_token, metrics_token = await self._ensure_garage_admin_secret(
            token=token,
            username=user.username,
        )

        garage_vol = await self._tapis.pods.get_or_create_volume(
            volume_config=pods_schemas.CreateTapisPodVolume(
                volume_id=f"{user.username}aistudiogarage",
                description=(
                    "Volume for AI Studio Garage S3 storage. Mount points "
                    "/var/lib/garage/meta, /var/lib/garage/data"
                ),
                size_limit=1024,
            ),
            client=self._tapis_client,
        )
        db_vol = await self._create_volume(
            volume_id=f"{user.username}aistudiodb",
            description="Volume for AI Studio shared PostgreSQL database.",
        )
        mlflow_pip_cache_vol = await self._create_volume(
            volume_id=f"{user.username}aistudiomlflowpipcache",
            description="Volume for AI Studio MLFlow pip cache.",
        )
        garage_pod = await self._tapis.pods.get_or_create_pod(
            pod_config=pods_schemas.CreateTapisPod(
                pod_id=f"{user.username}aistudiogarage",
                image="dxflrs/garage:090dbb412aff0afcbd42183ec12fa62c15bde58b",
                description="AI Studio Garage S3 Storage",
                volume_mounts={
                    "/etc/garage.toml": pods_schemas.TapisVolumeMount(
                        type="ephemeral",
                        config_content=self._garage.generate_garage_config(
                            rpc_secret, admin_token, metrics_token
                        ),
                        config_filename="garage.toml",
                    ),
                    "/var/lib/garage/meta": pods_schemas.TapisVolumeMount(
                        type="tapisvolume",
                        source_id=garage_vol.result.volume_id,
                        sub_path="/meta",
                    ),
                    "/var/lib/garage/data": pods_schemas.TapisVolumeMount(
                        type="tapisvolume",
                        source_id=garage_vol.result.volume_id,
                        sub_path="/data",
                    ),
                },
                networking={
                    "default": pods_schemas.TapisNetworking(
                        port=3900,
                        tapis_auth=True,
                        tapis_auth_allowed_users=[user.username],
                    ),
                    "admin": pods_schemas.TapisNetworking(
                        port=3903,
                        tapis_auth=True,
                        tapis_auth_allowed_users=[user.username],
                    ),
                },
            ),
            client=self._tapis_client,
        )

        garage_base_url = (
            f"https://{garage_pod.result.pod_id}-admin.pods."
            f"{tapis_config.tenant}.tapis.io"
        )
        artifacts_credentials = await self._ensure_garage_bucket_secret(
            secret_id=GARAGE_ARTIFACTS_SECRET_ID,
            token=token,
            username=user.username,
            garage_base_url=garage_base_url,
            admin_token=admin_token,
            bucket_kind="artifacts",
        )
        datasets_credentials = await self._ensure_garage_bucket_secret(
            secret_id=GARAGE_DATASETS_SECRET_ID,
            token=token,
            username=user.username,
            garage_base_url=garage_base_url,
            admin_token=admin_token,
            bucket_kind="datasets",
        )

        db_pod = await self._tapis.pods.get_or_create_pod(
            pod_config=pods_schemas.CreateTapisPod(
                pod_id=f"{user.username}aistudiodb",
                template="postgres:16@2024-12-04-18:28:04",
                description="AI Studio shared PostgreSQL database",
                volume_mounts={
                    "/var/lib/postgresql/data": pods_schemas.TapisVolumeMount(
                        type="tapisvolume",
                        source_id=db_vol.result.volume_id,
                        sub_path="/data",
                    ),
                },
            ),
            client=self._tapis_client,
        )

        db_creds = await self._tapis.pods.get_pod_credentials(
            pod_id=db_pod.result.pod_id,
            client=self._tapis_client,
        )
        db_internal_host = f"pods-tacc-{tapis_config.tenant}-{db_pod.result.pod_id}"
        garage_internal_host = (
            f"pods-tacc-{tapis_config.tenant}-{garage_pod.result.pod_id}"
        )

        await self._upsert_mlflow_pod(
            username=user.username,
            db_pod_id=db_pod.result.pod_id,
            db_internal_host=db_internal_host,
            db_username=db_creds.result.user_username,
            db_password=db_creds.result.user_password,
            garage_internal_host=garage_internal_host,
            artifacts_credentials=artifacts_credentials,
            pip_cache_volume_id=mlflow_pip_cache_vol.result.volume_id,
        )
        await self._upsert_gateway_pod(
            username=user.username,
            db_pod_id=db_pod.result.pod_id,
            db_internal_host=db_internal_host,
            db_username=db_creds.result.user_username,
            db_password=db_creds.result.user_password,
            garage_internal_host=garage_internal_host,
            datasets_credentials=datasets_credentials,
        )

        return user

    async def start_studio(self, token: SecretStr) -> StudioLifecycleResult:
        user = await self._tapis.auth.validate_token(token, self._tapis_client)
        changed, skipped = await self._run_pod_actions(
            username=user.username,
            pod_ids=self._studio_pod_ids(user.username),
            action="start",
        )
        return StudioLifecycleResult(
            username=user.username,
            changed=changed,
            skipped=skipped,
        )

    async def stop_studio(self, token: SecretStr) -> StudioLifecycleResult:
        user = await self._tapis.auth.validate_token(token, self._tapis_client)
        changed, skipped = await self._run_pod_actions(
            username=user.username,
            pod_ids=list(reversed(self._studio_pod_ids(user.username))),
            action="stop",
        )
        return StudioLifecycleResult(
            username=user.username,
            changed=changed,
            skipped=skipped,
        )

    async def delete_studio(self, token: SecretStr) -> StudioLifecycleResult:
        user = await self._tapis.auth.validate_token(token, self._tapis_client)
        changed, skipped = await self._run_pod_actions(
            username=user.username,
            pod_ids=list(reversed(self._studio_pod_ids(user.username))),
            action="delete",
        )
        deleted_volumes, skipped_volumes = await self._delete_volumes(user.username)
        return StudioLifecycleResult(
            username=user.username,
            changed=[*changed, *deleted_volumes],
            skipped=[*skipped, *skipped_volumes],
        )

    async def _create_volume(self, volume_id: str, description: str):
        return await self._tapis.pods.get_or_create_volume(
            volume_config=pods_schemas.CreateTapisPodVolume(
                volume_id=volume_id,
                description=description,
                size_limit=1024,
            ),
            client=self._tapis_client,
        )

    async def _run_pod_actions(
        self,
        username: str,
        pod_ids: list[str],
        action: Literal["start", "stop", "delete"],
    ) -> tuple[list[str], list[str]]:
        changed: list[str] = []
        skipped: list[str] = []
        action_map = {
            "start": self._tapis.pods.start_pod,
            "stop": self._tapis.pods.stop_pod,
            "delete": self._tapis.pods.delete_pod,
        }
        actor = action_map[action]

        for pod_id in pod_ids:
            try:
                await actor(pod_id, self._tapis_client)
                changed.append(pod_id)
            except UpstreamServiceError as error:
                if error.status_code == 404:
                    skipped.append(pod_id)
                    continue
                raise
        return changed, skipped

    async def _delete_volumes(self, username: str) -> tuple[list[str], list[str]]:
        changed: list[str] = []
        skipped: list[str] = []
        for volume_id in self._studio_volume_ids(username):
            try:
                await self._tapis.pods.delete_volume(volume_id, self._tapis_client)
                changed.append(volume_id)
            except UpstreamServiceError as error:
                if error.status_code == 404:
                    skipped.append(volume_id)
                    continue
                raise
        return changed, skipped

    @staticmethod
    def _studio_pod_ids(username: str) -> list[str]:
        return [
            f"{username}aistudiodb",
            f"{username}aistudiogarage",
            f"{username}aistudiomlflow",
            f"{username}aistudiogateway",
        ]

    @staticmethod
    def _studio_volume_ids(username: str) -> list[str]:
        return [
            f"{username}aistudiodb",
            f"{username}aistudiogarage",
            f"{username}aistudiomlflowpipcache",
        ]

    async def _ensure_garage_admin_secret(
        self, token: SecretStr, username: str
    ) -> tuple[SecretStr, SecretStr, SecretStr]:
        try:
            vault_admin = await self._tapis.vault.read_secret(
                secret_id=GARAGE_ADMIN_SECRET_ID,
                token=token,
                client=self._tapis_client,
            )
            return (
                SecretStr(vault_admin.result.secretMap["rpc_secret"]),
                SecretStr(vault_admin.result.secretMap["admin_token"]),
                SecretStr(vault_admin.result.secretMap["metrics_token"]),
            )
        except UpstreamServiceError as error:
            if error.status_code != 404:
                raise

        rpc_secret = SecretStr(secrets.token_hex(32))
        admin_token = SecretStr(secrets.token_hex(32))
        metrics_token = SecretStr(secrets.token_hex(32))
        await self._tapis.vault.write_secret(
            secret_id=GARAGE_ADMIN_SECRET_ID,
            secret=vault_schemas.WriteTapisSecret(
                tenant=tapis_config.tenant,
                user=username,
                data={
                    "rpc_secret": rpc_secret.get_secret_value(),
                    "admin_token": admin_token.get_secret_value(),
                    "metrics_token": metrics_token.get_secret_value(),
                },
            ),
            token=token,
            client=self._tapis_client,
        )
        return rpc_secret, admin_token, metrics_token

    async def _ensure_garage_bucket_secret(
        self,
        secret_id: str,
        token: SecretStr,
        username: str,
        garage_base_url: str,
        admin_token: SecretStr,
        bucket_kind: str,
    ) -> dict[str, str]:
        try:
            vault_secret = await self._tapis.vault.read_secret(
                secret_id=secret_id,
                token=token,
                client=self._tapis_client,
            )
            return vault_secret.result.secretMap
        except UpstreamServiceError as error:
            if error.status_code != 404:
                raise

        async with AsyncClient(base_url=garage_base_url) as garage_client:
            if bucket_kind == "artifacts":
                credentials = await self._garage.configure_artifacts(
                    client=garage_client,
                    garage_admin_token=admin_token,
                    tapis_token=token,
                )
            else:
                credentials = await self._garage.configure_datasets(
                    client=garage_client,
                    garage_admin_token=admin_token,
                    tapis_token=token,
                )

        data = {
            "access_key_id": credentials.access_key_id.get_secret_value(),
            "secret_access_key": credentials.secret_access_key.get_secret_value(),
            "bucket_id": credentials.bucket_id,
        }
        await self._tapis.vault.write_secret(
            secret_id=secret_id,
            secret=vault_schemas.WriteTapisSecret(
                tenant=tapis_config.tenant,
                user=username,
                data=data,
            ),
            token=token,
            client=self._tapis_client,
        )
        return data

    async def _upsert_mlflow_pod(
        self,
        username: str,
        db_pod_id: str,
        db_internal_host: str,
        db_username: str,
        db_password: SecretStr,
        garage_internal_host: str,
        artifacts_credentials: dict[str, str],
        pip_cache_volume_id: str,
    ) -> None:
        mlflow_config = pods_schemas.CreateTapisPod(
            pod_id=f"{username}aistudiomlflow",
            image="ghcr.io/mlflow/mlflow",
            description="AI Studio MLFlow",
            command=[
                "/bin/bash",
                "-c",
                "pip install psycopg2-binary boto3 "
                '&& python -c "'
                "import time, os, psycopg2\n"
                "uri = os.environ['MLFLOW_BACKEND_STORE_URI']\n"
                "for i in range(30):\n"
                "    try:\n"
                "        psycopg2.connect(uri).close(); print('PostgreSQL ready'); break\n"
                "    except Exception:\n"
                "        print(f'Waiting for PostgreSQL ({i+1}/30)...'); time.sleep(2)\n"
                "else:\n"
                "    raise RuntimeError('PostgreSQL not reachable after 60s')\n"
                '" '
                '&& mlflow db upgrade "$MLFLOW_BACKEND_STORE_URI" '
                "&& mlflow server",
            ],
            environment_variables={
                "MLFLOW_BACKEND_STORE_URI": (
                    f"postgresql://{db_username}:{db_password.get_secret_value()}"
                    f"@{db_internal_host}:5432/{db_pod_id}"
                ),
                "MLFLOW_S3_ENDPOINT_URL": f"http://{garage_internal_host}:3900",
                "MLFLOW_ARTIFACTS_DESTINATION": "s3://aistudio-artifacts/",
                "AWS_ACCESS_KEY_ID": artifacts_credentials["access_key_id"],
                "AWS_SECRET_ACCESS_KEY": artifacts_credentials["secret_access_key"],
                "AWS_DEFAULT_REGION": "garage",
                "MLFLOW_S3_IGNORE_TLS": "true",
                "MLFLOW_HOST": "0.0.0.0",
                "MLFLOW_PORT": "5000",
            },
            volume_mounts={
                "/root/.cache/pip": pods_schemas.TapisVolumeMount(
                    type="tapisvolume",
                    source_id=pip_cache_volume_id,
                    sub_path="/root/.cache/pip",
                ),
            },
            networking={
                "default": pods_schemas.TapisNetworking(
                    protocol=pods_schemas.TapisNetworkingProtocol.http,
                    port=5000,
                    tapis_auth=True,
                    tapis_auth_allowed_users=[username],
                ),
            },
        )

        try:
            await self._tapis.pods.get_pod(mlflow_config.pod_id, self._tapis_client)
            await self._tapis.pods.update_pod(
                pod_id=mlflow_config.pod_id,
                pod_config=mlflow_config,
                client=self._tapis_client,
            )
        except UpstreamServiceError as error:
            if error.status_code != 404:
                raise
            await self._tapis.pods.create_pod(mlflow_config, self._tapis_client)

    async def _upsert_gateway_pod(
        self,
        username: str,
        db_pod_id: str,
        db_internal_host: str,
        db_username: str,
        db_password: SecretStr,
        garage_internal_host: str,
        datasets_credentials: dict[str, str],
    ) -> None:
        mlflow_internal_host = (
            f"pods-tacc-{tapis_config.tenant}-{username}aistudiomlflow"
        )
        gateway_config = pods_schemas.CreateTapisPod(
            pod_id=f"{username}aistudiogateway",
            image=tapis_config.gateway_image,
            description="AI Studio Gateway",
            environment_variables={
                "AI_STUDIO_DATABASE_URL": (
                    f"postgresql+asyncpg://{db_username}:{db_password.get_secret_value()}"
                    f"@{db_internal_host}:5432/{db_pod_id}"
                ),
                "AI_STUDIO_GARAGE_URL": f"http://{garage_internal_host}:3903",
                "AI_STUDIO_MLFLOW_URL": f"http://{mlflow_internal_host}:5000",
                "AI_STUDIO_S3_ENDPOINT_URL": f"http://{garage_internal_host}:3900",
                "AI_STUDIO_DATASETS_DESTINATION": (
                    f"s3://{datasets_credentials['bucket_id']}/"
                ),
                "AI_STUDIO_S3_REGION": "garage",
                "AI_STUDIO_S3_ACCESS_KEY_ID": datasets_credentials["access_key_id"],
                "AI_STUDIO_S3_SECRET_ACCESS_KEY": datasets_credentials[
                    "secret_access_key"
                ],
            },
            networking={
                "default": pods_schemas.TapisNetworking(
                    protocol=pods_schemas.TapisNetworkingProtocol.http,
                    port=8000,
                    tapis_auth=True,
                    tapis_auth_allowed_users=[username],
                ),
            },
        )

        try:
            await self._tapis.pods.get_pod(gateway_config.pod_id, self._tapis_client)
            await self._tapis.pods.update_pod(
                pod_id=gateway_config.pod_id,
                pod_config=gateway_config,
                client=self._tapis_client,
            )
        except UpstreamServiceError as error:
            if error.status_code != 404:
                raise
            await self._tapis.pods.create_pod(gateway_config, self._tapis_client)
