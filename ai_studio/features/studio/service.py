"""Studio orchestration use cases."""

from dataclasses import dataclass
import secrets

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

        user = await self._tapis.auth.validate_token(token)
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
        prometheus_vol = await self._create_volume(
            volume_id=f"{user.username}aistudioprometheus",
            description="Volume for AI Studio Prometheus data.",
        )
        grafana_vol = await self._create_volume(
            volume_id=f"{user.username}aistudiografana",
            description="Volume for AI Studio Grafana data.",
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
        await self._ensure_garage_bucket_secret(
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
        prometheus_pod = await self._create_prometheus_pod(
            username=user.username,
            metrics_token=metrics_token,
            garage_internal_host=garage_internal_host,
            prometheus_volume_id=prometheus_vol.result.volume_id,
        )
        await self._create_grafana_pod(
            username=user.username,
            prometheus_pod_id=prometheus_pod.result.pod_id,
            grafana_volume_id=grafana_vol.result.volume_id,
        )

        return user

    async def _create_volume(self, volume_id: str, description: str):
        return await self._tapis.pods.get_or_create_volume(
            volume_config=pods_schemas.CreateTapisPodVolume(
                volume_id=volume_id,
                description=description,
                size_limit=1024,
            ),
            client=self._tapis_client,
        )

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

    async def _create_prometheus_pod(
        self,
        username: str,
        metrics_token: SecretStr,
        garage_internal_host: str,
        prometheus_volume_id: str,
    ):
        prometheus_config = (
            "global:\n"
            "  scrape_interval: 15s\n"
            "  evaluation_interval: 15s\n"
            "\n"
            "scrape_configs:\n"
            "  - job_name: garage\n"
            "    metrics_path: /metrics\n"
            "    scheme: http\n"
            "    authorization:\n"
            f"      credentials: {metrics_token.get_secret_value()}\n"
            "    static_configs:\n"
            f"      - targets: ['{garage_internal_host}:3903']\n"
        )
        return await self._tapis.pods.get_or_create_pod(
            pod_config=pods_schemas.CreateTapisPod(
                pod_id=f"{username}aistudioprometheus",
                image="prom/prometheus:latest",
                description="AI Studio Prometheus",
                volume_mounts={
                    "/etc/prometheus/prometheus.yml": pods_schemas.TapisVolumeMount(
                        type="ephemeral",
                        config_content=prometheus_config,
                        config_filename="prometheus.yml",
                    ),
                    "/prometheus": pods_schemas.TapisVolumeMount(
                        type="tapisvolume",
                        source_id=prometheus_volume_id,
                        sub_path="/data",
                    ),
                },
            ),
            client=self._tapis_client,
        )

    async def _create_grafana_pod(
        self,
        username: str,
        prometheus_pod_id: str,
        grafana_volume_id: str,
    ) -> None:
        prometheus_internal_host = (
            f"pods-tacc-{tapis_config.tenant}-{prometheus_pod_id}"
        )
        grafana_datasource_config = (
            "apiVersion: 1\n"
            "\n"
            "datasources:\n"
            "  - name: Prometheus\n"
            "    type: prometheus\n"
            f"    url: http://{prometheus_internal_host}:9090\n"
            "    access: proxy\n"
            "    isDefault: true\n"
        )
        await self._tapis.pods.get_or_create_pod(
            pod_config=pods_schemas.CreateTapisPod(
                pod_id=f"{username}aistudiografana",
                image="grafana/grafana:latest",
                description="AI Studio Grafana",
                volume_mounts={
                    "/etc/grafana/provisioning/datasources/datasources.yml": (
                        pods_schemas.TapisVolumeMount(
                            type="ephemeral",
                            config_content=grafana_datasource_config,
                            config_filename="datasources.yml",
                        )
                    ),
                    "/var/lib/grafana": pods_schemas.TapisVolumeMount(
                        type="tapisvolume",
                        source_id=grafana_volume_id,
                        sub_path="/data",
                    ),
                },
            ),
            client=self._tapis_client,
        )
