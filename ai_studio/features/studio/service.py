"""Studio orchestration use cases."""

import asyncio
import hashlib
import logging
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
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
from ai_studio.exceptions import InvalidResponseError, UpstreamServiceError
from ai_studio.features.studio.schemas import (
    StudioLifecycleResult,
    StudioPodResourceOptions,
    StudioProvisionConfig,
    StudioProvisionRequest,
    resolve_studio_provision_config,
)

logger = logging.getLogger("ai_studio.features.studio")

GARAGE_ADMIN_SECRET_ID = "aistudio-garage-admin"
GARAGE_ARTIFACTS_SECRET_ID = "aistudio-garage-artifacts"
GARAGE_DATASETS_SECRET_ID = "aistudio-garage-datasets"
# Pod IDs, volume IDs, Traefik router names, and route paths all share this
# prefix, so keep it lowercase, short, and free of DNS/path-sensitive characters.
_SAFE_RESOURCE_ID_RE = re.compile(r"^[a-z0-9]{1,40}$")
_UNSAFE_RESOURCE_CHARS_RE = re.compile(r"[^a-z0-9]+")


def _resource_id_for_username(username: str) -> str:
    """Return the stable resource prefix for a Tapis username.

    Plain TACC usernames such as ``alice`` are already safe and stay unchanged.
    Usernames containing punctuation, such as email addresses, are slugified and
    get a short hash suffix so different usernames do not collapse to the same
    resource prefix after unsafe characters are removed.
    """
    normalized = username.strip().lower()
    if _SAFE_RESOURCE_ID_RE.fullmatch(normalized):
        return normalized

    slug = _UNSAFE_RESOURCE_CHARS_RE.sub("", normalized)
    if not slug:
        raise ValueError(f"Cannot derive resource id from Tapis username: {username!r}")

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:32]}{digest}"


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
        http_client: AsyncClient,
        lifecycle_locks: dict[str, asyncio.Lock] | None = None,
    ):
        """Store adapter dependencies and the shared Tapis HTTP client."""
        self._tapis = tapis
        self._garage = garage
        self._http_client = http_client
        self._lifecycle_locks = lifecycle_locks if lifecycle_locks is not None else {}

    async def provision_studio(
        self,
        token: SecretStr,
        request: StudioProvisionRequest | None = None,
    ) -> auth_schemas.TapisUserInfo:
        """Provision initial AI Studio resources for the authenticated user."""

        provision_config = resolve_studio_provision_config(request)
        user = await self._tapis.auth.validate_token(token, self._http_client)
        resource_id = _resource_id_for_username(user.username)
        logger.info(
            (
                "studio.provision.start username=%s resource_id=%s profile=%s "
                "volumes.garage=%d volumes.postgres=%d volumes.mlflow_pip_cache=%d "
                "resources.mlflow.cpu=%d/%d resources.mlflow.mem=%d/%d "
                "resources.mlflow.gpus=%d "
                "resources.datasets.cpu=%d/%d resources.datasets.mem=%d/%d "
                "resources.datasets.gpus=%d "
                "time_to_stop_default=%d"
            ),
            user.username,
            resource_id,
            provision_config.profile,
            provision_config.volumes.garage.size_limit,
            provision_config.volumes.postgres.size_limit,
            provision_config.volumes.mlflow_pip_cache.size_limit,
            provision_config.resources.mlflow.cpu_request,
            provision_config.resources.mlflow.cpu_limit,
            provision_config.resources.mlflow.mem_request,
            provision_config.resources.mlflow.mem_limit,
            provision_config.resources.mlflow.gpus,
            provision_config.resources.datasets.cpu_request,
            provision_config.resources.datasets.cpu_limit,
            provision_config.resources.datasets.mem_request,
            provision_config.resources.datasets.mem_limit,
            provision_config.resources.datasets.gpus,
            provision_config.lifecycle.time_to_stop_default,
        )
        async with self._lifecycle_lock(resource_id):
            # Provisioning creates several dependent resources and writes the
            # user's route file, so all lifecycle mutations for this resource
            # must run one-at-a-time.
            try:
                result = await self._provision_studio_for_user(
                    token=token,
                    username=user.username,
                    resource_id=resource_id,
                    provision_config=provision_config,
                )
            except Exception:
                logger.exception(
                    "studio.provision.failed username=%s resource_id=%s",
                    user.username,
                    resource_id,
                )
                raise
            logger.info(
                "studio.provision.done username=%s resource_id=%s",
                user.username,
                resource_id,
            )
            return result

    async def _provision_studio_for_user(
        self,
        token: SecretStr,
        username: str,
        resource_id: str,
        provision_config: StudioProvisionConfig,
    ) -> auth_schemas.TapisUserInfo:
        """Create the full pod, volume, secret, and route-file stack for a user."""
        rpc_secret, admin_token, metrics_token = await self._ensure_garage_admin_secret(
            token=token,
            username=username,
        )

        garage_vol = await self._tapis.pods.get_or_create_volume(
            volume_config=pods_schemas.CreateTapisPodVolume(
                volume_id=f"{resource_id}aistudiogarage",
                description=(
                    "Volume for AI Studio Garage S3 storage. Mount points "
                    "/var/lib/garage/meta, /var/lib/garage/data"
                ),
                size_limit=provision_config.volumes.garage.size_limit,
            ),
            client=self._http_client,
        )
        self._require_volume_size(
            volume_id=garage_vol.result.volume_id,
            actual_size_limit=garage_vol.result.size_limit,
            requested_size_limit=provision_config.volumes.garage.size_limit,
        )
        db_vol = await self._create_volume(
            volume_id=f"{resource_id}aistudiodb",
            description="Volume for AI Studio shared PostgreSQL database.",
            size_limit=provision_config.volumes.postgres.size_limit,
        )
        mlflow_pip_cache_vol = await self._create_volume(
            volume_id=f"{resource_id}aistudiomlflowpipcache",
            description="Volume for AI Studio MLFlow pip cache.",
            size_limit=provision_config.volumes.mlflow_pip_cache.size_limit,
        )
        garage_pod = await self._upsert_pod(
            pods_schemas.CreateTapisPod(
                pod_id=f"{resource_id}aistudiogarage",
                image=tapis_config.garage_image,
                description="AI Studio Garage S3 Storage",
                time_to_stop_default=provision_config.lifecycle.time_to_stop_default,
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
                        tapis_auth_allowed_users=[username],
                    ),
                    "admin": pods_schemas.TapisNetworking(
                        port=3903,
                        tapis_auth=True,
                        tapis_auth_allowed_users=[username],
                    ),
                },
            ),
        )

        garage_base_url = (
            f"https://{garage_pod.result.pod_id}-admin.pods."
            f"{tapis_config.tenant}.tapis.io"
        )
        artifacts_credentials = await self._ensure_garage_bucket_secret(
            secret_id=GARAGE_ARTIFACTS_SECRET_ID,
            token=token,
            username=username,
            garage_base_url=garage_base_url,
            admin_token=admin_token,
            bucket_kind="artifacts",
        )
        datasets_credentials = await self._ensure_garage_bucket_secret(
            secret_id=GARAGE_DATASETS_SECRET_ID,
            token=token,
            username=username,
            garage_base_url=garage_base_url,
            admin_token=admin_token,
            bucket_kind="datasets",
        )

        db_pod = await self._upsert_pod(
            pods_schemas.CreateTapisPod(
                pod_id=f"{resource_id}aistudiodb",
                template=tapis_config.postgres_template,
                description="AI Studio shared PostgreSQL database",
                time_to_stop_default=provision_config.lifecycle.time_to_stop_default,
                volume_mounts={
                    "/var/lib/postgresql/data": pods_schemas.TapisVolumeMount(
                        type="tapisvolume",
                        source_id=db_vol.result.volume_id,
                        sub_path="/data",
                    ),
                },
            ),
        )

        db_creds = await self._tapis.pods.get_pod_credentials(
            pod_id=db_pod.result.pod_id,
            client=self._http_client,
        )
        db_internal_host = f"pods-tacc-{tapis_config.tenant}-{db_pod.result.pod_id}"
        garage_internal_host = (
            f"pods-tacc-{tapis_config.tenant}-{garage_pod.result.pod_id}"
        )

        await self._upsert_mlflow_pod(
            resource_id=resource_id,
            allowed_username=username,
            db_pod_id=db_pod.result.pod_id,
            db_internal_host=db_internal_host,
            db_username=db_creds.result.user_username,
            db_password=db_creds.result.user_password,
            garage_internal_host=garage_internal_host,
            artifacts_credentials=artifacts_credentials,
            pip_cache_volume_id=mlflow_pip_cache_vol.result.volume_id,
            resources=provision_config.resources.mlflow,
            time_to_stop_default=provision_config.lifecycle.time_to_stop_default,
        )
        await self._upsert_datasets_pod(
            resource_id=resource_id,
            db_pod_id=db_pod.result.pod_id,
            db_internal_host=db_internal_host,
            db_username=db_creds.result.user_username,
            db_password=db_creds.result.user_password,
            garage_internal_host=garage_internal_host,
            datasets_credentials=datasets_credentials,
            resources=provision_config.resources.datasets,
            time_to_stop_default=provision_config.lifecycle.time_to_stop_default,
        )
        self._write_traefik_route_file(resource_id)

        return auth_schemas.TapisUserInfo(username=username)

    async def start_studio(self, token: SecretStr) -> StudioLifecycleResult:
        """Start a user's studio pods and ensure their route file exists."""
        user = await self._tapis.auth.validate_token(token, self._http_client)
        resource_id = _resource_id_for_username(user.username)
        logger.info(
            "studio.start username=%s resource_id=%s",
            user.username,
            resource_id,
        )
        async with self._lifecycle_lock(resource_id):
            changed, skipped = await self._run_pod_actions(
                username=resource_id,
                pod_ids=self._studio_pod_ids(resource_id),
                action="start",
            )
            self._write_traefik_route_file(resource_id)
        logger.info(
            "studio.start.done username=%s changed=%d skipped=%d",
            user.username,
            len(changed),
            len(skipped),
        )
        return StudioLifecycleResult(
            username=user.username,
            changed=changed,
            skipped=skipped,
        )

    async def stop_studio(self, token: SecretStr) -> StudioLifecycleResult:
        """Stop a user's studio pods without deleting data or route files."""
        user = await self._tapis.auth.validate_token(token, self._http_client)
        resource_id = _resource_id_for_username(user.username)
        logger.info(
            "studio.stop username=%s resource_id=%s",
            user.username,
            resource_id,
        )
        async with self._lifecycle_lock(resource_id):
            changed, skipped = await self._run_pod_actions(
                username=resource_id,
                pod_ids=list(reversed(self._studio_pod_ids(resource_id))),
                action="stop",
            )
        logger.info(
            "studio.stop.done username=%s changed=%d skipped=%d",
            user.username,
            len(changed),
            len(skipped),
        )
        return StudioLifecycleResult(
            username=user.username,
            changed=changed,
            skipped=skipped,
        )

    async def delete_studio(self, token: SecretStr) -> StudioLifecycleResult:
        """Delete a user's studio pods, volumes, and route file."""
        user = await self._tapis.auth.validate_token(token, self._http_client)
        resource_id = _resource_id_for_username(user.username)
        logger.info(
            "studio.delete username=%s resource_id=%s",
            user.username,
            resource_id,
        )
        async with self._lifecycle_lock(resource_id):
            changed, skipped = await self._run_pod_actions(
                username=resource_id,
                pod_ids=list(reversed(self._studio_pod_ids(resource_id))),
                action="delete",
            )
            deleted_volumes, skipped_volumes = await self._delete_volumes(resource_id)
            self._remove_traefik_route_file(resource_id)
        logger.info(
            "studio.delete.done username=%s pods_changed=%d volumes_changed=%d",
            user.username,
            len(changed),
            len(deleted_volumes),
        )
        return StudioLifecycleResult(
            username=user.username,
            changed=[*changed, *deleted_volumes],
            skipped=[*skipped, *skipped_volumes],
        )

    async def _create_volume(self, volume_id: str, description: str, size_limit: int):
        """Create or retrieve a volume and reject existing size mismatches."""
        volume = await self._tapis.pods.get_or_create_volume(
            volume_config=pods_schemas.CreateTapisPodVolume(
                volume_id=volume_id,
                description=description,
                size_limit=size_limit,
            ),
            client=self._http_client,
        )
        self._require_volume_size(
            volume_id=volume.result.volume_id,
            actual_size_limit=volume.result.size_limit,
            requested_size_limit=size_limit,
        )
        return volume

    @staticmethod
    def _require_volume_size(
        volume_id: str,
        actual_size_limit: int,
        requested_size_limit: int,
    ) -> None:
        """Raise a conflict when an existing volume has the wrong size."""
        if actual_size_limit == requested_size_limit:
            return
        logger.warning(
            (
                "studio.volume.size_mismatch volume_id=%s actual_size_limit=%d "
                "requested_size_limit=%d"
            ),
            volume_id,
            actual_size_limit,
            requested_size_limit,
        )
        raise UpstreamServiceError(
            status_code=409,
            detail={
                "message": "Provisioned volume size does not match requested size",
                "details": (
                    f"Volume '{volume_id}' already exists with size_limit "
                    f"{actual_size_limit}; requested {requested_size_limit}. "
                    "Delete and re-provision the studio or use the existing size."
                ),
            },
        )

    def _lifecycle_lock(self, resource_id: str) -> asyncio.Lock:
        """Return the in-process mutex for one studio resource.

        It prevents overlapping provision/start/stop/delete calls for the same
        resource_id from racing on pods, volumes, and
        Traefik route files. Different resource IDs use different locks.
        """
        lock = self._lifecycle_locks.get(resource_id)
        if lock is None:
            lock = asyncio.Lock()
            self._lifecycle_locks[resource_id] = lock
        return lock

    @staticmethod
    def _require_secret_keys(
        secret_id: str,
        secret_map: dict[str, str],
        required_keys: tuple[str, ...],
    ) -> dict[str, str]:
        """Require a Vault secret map to contain all expected non-empty keys."""
        missing = [key for key in required_keys if not secret_map.get(key)]
        if missing:
            raise InvalidResponseError(
                status_code=502,
                detail={
                    "message": "Vault secret is missing required keys",
                    "details": (
                        f"Secret '{secret_id}' is missing required key(s): "
                        f"{', '.join(missing)}. The stored secret may be incomplete; "
                        "delete or repair it before retrying provisioning."
                    ),
                },
            )
        return secret_map

    async def _run_pod_actions(
        self,
        username: str,
        pod_ids: list[str],
        action: Literal["start", "stop", "delete"],
    ) -> tuple[list[str], list[str]]:
        """Apply one lifecycle action to pods, treating 404s as skipped."""
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
                await actor(pod_id, self._http_client)
                changed.append(pod_id)
            except UpstreamServiceError as error:
                if error.status_code == 404:
                    logger.info(
                        "studio.pod_action.skipped action=%s pod_id=%s reason=not_found",
                        action,
                        pod_id,
                    )
                    skipped.append(pod_id)
                    continue
                raise
        return changed, skipped

    async def _delete_volumes(self, username: str) -> tuple[list[str], list[str]]:
        """Delete all studio volumes for a resource, treating 404s as skipped."""
        changed: list[str] = []
        skipped: list[str] = []
        for volume_id in self._studio_volume_ids(username):
            try:
                await self._tapis.pods.delete_volume(volume_id, self._http_client)
                changed.append(volume_id)
            except UpstreamServiceError as error:
                if error.status_code == 404:
                    skipped.append(volume_id)
                    continue
                raise
        return changed, skipped

    @staticmethod
    def _studio_pod_ids(username: str) -> list[str]:
        """Return studio pod IDs in dependency startup order."""
        return [
            f"{username}aistudiodb",
            f"{username}aistudiogarage",
            f"{username}aistudiomlflow",
            f"{username}aistudiodatasets",
        ]

    @staticmethod
    def _studio_volume_ids(username: str) -> list[str]:
        """Return all studio volume IDs for a resource."""
        return [
            f"{username}aistudiodb",
            f"{username}aistudiogarage",
            f"{username}aistudiomlflowpipcache",
        ]

    @staticmethod
    def _traefik_route_file_path(username: str) -> Path:
        """Return the dynamic Traefik route file path for a resource."""
        return (
            tapis_config.traefik_dynamic_dir
            / f"{_resource_id_for_username(username)}.yml"
        )

    def _write_traefik_route_file(self, username: str) -> None:
        """Atomically write the user's Traefik dynamic route file."""
        username = _resource_id_for_username(username)
        route_file = self._traefik_route_file_path(username)
        logger.info("studio.traefik.write path=%s", route_file)
        route_file.parent.mkdir(parents=True, exist_ok=True)
        content = self._render_traefik_route_file(username)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=route_file.parent,
            prefix=f".{route_file.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(content)
            os.replace(tmp_path, route_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _remove_traefik_route_file(self, username: str) -> None:
        """Remove the user's Traefik dynamic route file if it exists."""
        route_file = self._traefik_route_file_path(username)
        logger.info("studio.traefik.remove path=%s", route_file)
        route_file.unlink(missing_ok=True)

    @staticmethod
    def _render_traefik_route_file(username: str) -> str:
        """Render Traefik routers, middleware, and services for a resource."""
        username = _resource_id_for_username(username)
        datasets_internal_host = (
            f"pods-tacc-{tapis_config.tenant}-{username}aistudiodatasets"
        )
        mlflow_internal_host = (
            f"pods-tacc-{tapis_config.tenant}-{username}aistudiomlflow"
        )

        return (
            "http:\n"
            "  routers:\n"
            f"    {username}-datasets:\n"
            f"      rule: Host(`{tapis_config.traefik_public_host}`) && "
            f"PathPrefix(`/u/{username}/datasets`)\n"
            "      priority: 100\n"
            "      entryPoints:\n"
            "        - web\n"
            "      middlewares:\n"
            "        - security-headers\n"
            "        - datasets-buffer\n"
            f"        - strip-{username}-datasets-prefix\n"
            f"      service: {username}-datasets\n\n"
            f"    {username}-mlflow:\n"
            f"      rule: Host(`{tapis_config.traefik_public_host}`) && "
            f"PathPrefix(`/u/{username}/mlflow`)\n"
            "      priority: 100\n"
            "      entryPoints:\n"
            "        - web\n"
            "      middlewares:\n"
            "        - security-headers\n"
            f"        - strip-{username}-mlflow-prefix\n"
            f"      service: {username}-mlflow\n\n"
            "  middlewares:\n"
            "    datasets-buffer:\n"
            "      buffering:\n"
            "        maxRequestBodyBytes: 10737418240\n"
            "        memRequestBodyBytes: 2097152\n\n"
            f"    strip-{username}-datasets-prefix:\n"
            "      stripPrefix:\n"
            "        prefixes:\n"
            f"          - /u/{username}/datasets\n\n"
            f"    strip-{username}-mlflow-prefix:\n"
            "      stripPrefix:\n"
            "        prefixes:\n"
            f"          - /u/{username}/mlflow\n\n"
            "  services:\n"
            f"    {username}-datasets:\n"
            "      loadBalancer:\n"
            "        healthCheck:\n"
            "          path: /health\n"
            "          interval: 10s\n"
            "          timeout: 3s\n"
            "        servers:\n"
            f"          - url: http://{datasets_internal_host}:5000\n\n"
            f"    {username}-mlflow:\n"
            "      loadBalancer:\n"
            "        servers:\n"
            f"          - url: http://{mlflow_internal_host}:5000\n"
        )

    async def _ensure_garage_admin_secret(
        self, token: SecretStr, username: str
    ) -> tuple[SecretStr, SecretStr, SecretStr]:
        """Read or create the shared Garage admin secret in Tapis Vault."""
        try:
            vault_admin = await self._tapis.vault.read_secret(
                secret_id=GARAGE_ADMIN_SECRET_ID,
                token=token,
                client=self._http_client,
            )
            secret_map = self._require_secret_keys(
                GARAGE_ADMIN_SECRET_ID,
                vault_admin.result.secretMap,
                ("rpc_secret", "admin_token", "metrics_token"),
            )
            return (
                SecretStr(secret_map["rpc_secret"]),
                SecretStr(secret_map["admin_token"]),
                SecretStr(secret_map["metrics_token"]),
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
            client=self._http_client,
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
        """Read or create Garage bucket credentials and persist them in Vault."""
        try:
            vault_secret = await self._tapis.vault.read_secret(
                secret_id=secret_id,
                token=token,
                client=self._http_client,
            )
            return self._require_secret_keys(
                secret_id,
                vault_secret.result.secretMap,
                ("access_key_id", "secret_access_key", "bucket_id"),
            )
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
            client=self._http_client,
        )
        return data

    async def _upsert_pod(
        self,
        pod_config: pods_schemas.CreateTapisPod,
    ) -> pods_schemas.TapisPodApiResponse:
        try:
            await self._tapis.pods.get_pod(pod_config.pod_id, self._http_client)
            return await self._tapis.pods.update_pod(
                pod_id=pod_config.pod_id,
                pod_config=pod_config,
                client=self._http_client,
            )
        except UpstreamServiceError as error:
            if error.status_code != 404:
                raise
            return await self._tapis.pods.create_pod(pod_config, self._http_client)

    async def _upsert_mlflow_pod(
        self,
        resource_id: str,
        allowed_username: str,
        db_pod_id: str,
        db_internal_host: str,
        db_username: str,
        db_password: SecretStr,
        garage_internal_host: str,
        artifacts_credentials: dict[str, str],
        pip_cache_volume_id: str,
        resources: StudioPodResourceOptions,
        time_to_stop_default: int,
    ) -> None:
        """Create or update the MLflow pod with DB and artifact-store wiring."""
        mlflow_config = pods_schemas.CreateTapisPod(
            pod_id=f"{resource_id}aistudiomlflow",
            image=tapis_config.mlflow_image,
            description="AI Studio MLFlow",
            time_to_stop_default=time_to_stop_default,
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
                    tapis_auth_allowed_users=[allowed_username],
                ),
            },
            resources=self._to_tapis_resources(resources),
        )

        await self._upsert_pod(mlflow_config)

    async def _upsert_datasets_pod(
        self,
        resource_id: str,
        db_pod_id: str,
        db_internal_host: str,
        db_username: str,
        db_password: SecretStr,
        garage_internal_host: str,
        datasets_credentials: dict[str, str],
        resources: StudioPodResourceOptions,
        time_to_stop_default: int,
    ) -> None:
        """Create or update the datasets API pod with DB and object-store wiring."""
        datasets_config = pods_schemas.CreateTapisPod(
            pod_id=f"{resource_id}aistudiodatasets",
            image=tapis_config.datasets_image,
            description="AI Studio Datasets",
            time_to_stop_default=time_to_stop_default,
            environment_variables={
                "AI_STUDIO_DATABASE_URL": (
                    f"postgresql+asyncpg://{db_username}:{db_password.get_secret_value()}"
                    f"@{db_internal_host}:5432/{db_pod_id}"
                ),
                "AI_STUDIO_GARAGE_URL": f"http://{garage_internal_host}:3903",
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
            resources=self._to_tapis_resources(resources),
        )

        await self._upsert_pod(datasets_config)

    @staticmethod
    def _to_tapis_resources(
        resources: StudioPodResourceOptions,
    ) -> pods_schemas.TapisResources:
        """Convert public provisioning resource options into Tapis schema fields."""
        return pods_schemas.TapisResources(
            cpu_request=resources.cpu_request,
            cpu_limit=resources.cpu_limit,
            mem_request=resources.mem_request,
            mem_limit=resources.mem_limit,
            gpus=resources.gpus,
        )
