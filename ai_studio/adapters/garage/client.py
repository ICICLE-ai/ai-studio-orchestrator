"""Garage object storage configuration and API client utilities."""

import httpx
import tomlkit
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from ai_studio.core.retry import with_retry
from ai_studio.exceptions import (
    InvalidResponseError,
    ServiceUnavailableError,
    UpstreamServiceError,
)
from ai_studio.adapters.garage.schemas import (
    AllowGarageBucketKeyPayload,
    AllowGarageBucketKeyResponse,
    ApplyGarageClusterLayoutPayload,
    ApplyGarageClusterLayoutResponse,
    CreateGarageBucketPayload,
    CreateGarageBucketResponse,
    CreateGarageKeyPayload,
    CreateGarageKeyResponse,
    DeleteGarageKeyPayload,
    GarageBucketCredentials,
    GarageBucketKeyPermissions,
    GetGarageClusterStatusResponse,
    GetGarageHealthResponse,
    ListGarageBucketsResponseItem,
    ListGarageKeysResponseItem,
    UpdateGarageClusterLayoutPayload,
    UpdateGarageClusterLayoutResponse,
    UpdateGarageClusterLayoutRolePayload,
)


class GarageClient:
    """Build Garage config files and call Garage admin API endpoints."""

    async def _make_request[T: BaseModel](
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        response_model: type[T],
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
        json_data: dict | None = None,
    ) -> T:
        """Send an HTTP request to Garage and validate the response payload."""
        try:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
                headers={
                    "Authorization": (
                        f"Bearer {garage_admin_token.get_secret_value()}"
                    ),
                    "X-Tapis-Token": tapis_token.get_secret_value(),
                },
            )
            if response.status_code not in (200, 201):
                raise UpstreamServiceError(
                    status_code=response.status_code,
                    detail={
                        "message": "Garage API returned an error",
                        "details": response.text,
                    },
                )
            return response_model.model_validate(response.json())
        except httpx.RequestError as error:
            raise ServiceUnavailableError(
                status_code=503,
                detail={
                    "message": "Unable to reach Garage service",
                    "details": f"{type(error).__name__}: {str(error)}",
                },
            )
        except ValidationError as error:
            errors = error.errors()
            error_details = [f"{err['loc'][-1]}: {err['msg']}" for err in errors]
            raise InvalidResponseError(
                status_code=502,
                detail={
                    "message": "Garage API returned invalid response format",
                    "details": error_details,
                },
            )

    def generate_garage_config(
        self,
        rpc_secret: SecretStr,
        admin_token: SecretStr,
        metrics_token: SecretStr,
    ) -> str:
        """Generate a Garage TOML configuration with runtime credentials."""
        doc = tomlkit.document()
        doc.add("metadata_dir", tomlkit.item("/var/lib/garage/meta"))
        doc.add("data_dir", tomlkit.item("/var/lib/garage/data"))
        doc.add("db_engine", tomlkit.item("lmdb"))
        doc.add("metadata_auto_snapshot_interval", tomlkit.item("6h"))
        doc.add("replication_factor", tomlkit.item(1))
        doc.add("rpc_bind_addr", tomlkit.item("[::]:3901"))
        doc.add(
            "rpc_public_addr",
            tomlkit.item("aistudiogarage-rpc.pods.icicleai.tapis.io:3901"),
        )
        doc.add("rpc_secret", tomlkit.item(rpc_secret.get_secret_value()))

        s3_api = tomlkit.table()
        s3_api.add("s3_region", tomlkit.item("garage"))
        s3_api.add("api_bind_addr", tomlkit.item("[::]:3900"))
        s3_api.add("root_domain", tomlkit.item(".aistudiogarage.pods.icicleai.tapis.io"))
        doc.add("s3_api", s3_api)

        s3_web = tomlkit.table()
        s3_web.add("bind_addr", tomlkit.item("[::]:3902"))
        s3_web.add(
            "root_domain", tomlkit.item(".aistudiogarage-web.pods.icicleai.tapis.io")
        )
        s3_web.add("index", tomlkit.item("index.html"))
        doc.add("s3_web", s3_web)

        k2v_api = tomlkit.table()
        k2v_api.add("api_bind_addr", tomlkit.item("[::]:3904"))
        doc.add("k2v_api", k2v_api)

        admin = tomlkit.table()
        admin.add("api_bind_addr", tomlkit.item("[::]:3903"))
        admin.add("admin_token", tomlkit.item(admin_token.get_secret_value()))
        admin.add("metrics_token", tomlkit.item(metrics_token.get_secret_value()))
        doc.add("admin", admin)

        return tomlkit.dumps(doc)

    async def get_health(
        self, client: httpx.AsyncClient, garage_admin_token: SecretStr, tapis_token: SecretStr
    ) -> GetGarageHealthResponse:
        return await self._make_request(
            client=client,
            method="GET",
            url="/v2/GetClusterHealth",
            response_model=GetGarageHealthResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def get_cluster_status(
        self, client: httpx.AsyncClient, garage_admin_token: SecretStr, tapis_token: SecretStr
    ) -> GetGarageClusterStatusResponse:
        return await self._make_request(
            client=client,
            method="GET",
            url="/v2/GetClusterStatus",
            response_model=GetGarageClusterStatusResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def update_cluster_layout(
        self,
        payload: UpdateGarageClusterLayoutPayload,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> UpdateGarageClusterLayoutResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v2/UpdateClusterLayout",
            json_data=payload.model_dump(),
            response_model=UpdateGarageClusterLayoutResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def get_cluster_layout(
        self,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> UpdateGarageClusterLayoutResponse:
        return await self._make_request(
            client=client,
            method="GET",
            url="/v2/GetClusterLayout",
            response_model=UpdateGarageClusterLayoutResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def apply_cluster_layout(
        self,
        payload: ApplyGarageClusterLayoutPayload,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> ApplyGarageClusterLayoutResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v2/ApplyClusterLayout",
            json_data=payload.model_dump(),
            response_model=ApplyGarageClusterLayoutResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def create_key(
        self,
        payload: CreateGarageKeyPayload,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> CreateGarageKeyResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v2/CreateKey",
            json_data=payload.model_dump(),
            response_model=CreateGarageKeyResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def create_bucket(
        self,
        payload: CreateGarageBucketPayload,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> CreateGarageBucketResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v2/CreateBucket",
            json_data=payload.model_dump(),
            response_model=CreateGarageBucketResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def allow_bucket_key(
        self,
        payload: AllowGarageBucketKeyPayload,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> AllowGarageBucketKeyResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url="/v2/AllowBucketKey",
            json_data=payload.model_dump(),
            response_model=AllowGarageBucketKeyResponse,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def _make_list_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        item_type: type,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> list:
        """Send a GET request to a Garage list endpoint that returns a JSON array."""
        try:
            response = await client.request(
                method="GET",
                url=url,
                headers={
                    "Authorization": (
                        f"Bearer {garage_admin_token.get_secret_value()}"
                    ),
                    "X-Tapis-Token": tapis_token.get_secret_value(),
                },
            )
            if response.status_code not in (200, 201):
                raise UpstreamServiceError(
                    status_code=response.status_code,
                    detail={
                        "message": "Garage API returned an error",
                        "details": response.text,
                    },
                )
            adapter = TypeAdapter(list[item_type])
            return adapter.validate_python(response.json())
        except httpx.RequestError as error:
            raise ServiceUnavailableError(
                status_code=503,
                detail={
                    "message": "Unable to reach Garage service",
                    "details": f"{type(error).__name__}: {str(error)}",
                },
            )
        except ValidationError as error:
            errors = error.errors()
            error_details = [f"{err['loc'][-1]}: {err['msg']}" for err in errors]
            raise InvalidResponseError(
                status_code=502,
                detail={
                    "message": "Garage API returned invalid response format",
                    "details": error_details,
                },
            )

    async def list_keys(
        self,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> list[ListGarageKeysResponseItem]:
        return await self._make_list_request(
            client=client,
            url="/v2/ListKeys",
            item_type=ListGarageKeysResponseItem,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def list_buckets(
        self,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> list[ListGarageBucketsResponseItem]:
        return await self._make_list_request(
            client=client,
            url="/v2/ListBuckets",
            item_type=ListGarageBucketsResponseItem,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

    async def delete_key(
        self,
        payload: DeleteGarageKeyPayload,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
    ) -> None:
        """Delete a Garage access key."""
        try:
            response = await client.request(
                method="POST",
                url=f"/v2/DeleteKey?id={payload.accessKeyId}",
                headers={
                    "Authorization": (
                        f"Bearer {garage_admin_token.get_secret_value()}"
                    ),
                    "X-Tapis-Token": tapis_token.get_secret_value(),
                },
            )
            if response.status_code not in (200, 204):
                raise UpstreamServiceError(
                    status_code=response.status_code,
                    detail={
                        "message": "Garage API returned an error",
                        "details": response.text,
                    },
                )
        except httpx.RequestError as error:
            raise ServiceUnavailableError(
                status_code=503,
                detail={
                    "message": "Unable to reach Garage service",
                    "details": f"{type(error).__name__}: {str(error)}",
                },
            )

    async def _ensure_layout(
        self,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
        layout_zone: str,
        layout_capacity: int,
    ) -> None:
        """Wait for Garage health and apply cluster layout if not already done."""
        common = dict(
            client=client,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

        await with_retry(
            GarageClient.get_health,
            **common,
            max_attempts=30,
            base_delay=2.0,
            retryable=(ServiceUnavailableError, UpstreamServiceError),
        )

        status = await self.get_cluster_status(**common)
        node_id = status.nodes[0].id

        layout = await self.get_cluster_layout(**common)
        layout_applied = len(layout.roles) > 0 and len(layout.stagedRoleChanges) == 0

        if not layout_applied:
            await self.update_cluster_layout(
                payload=UpdateGarageClusterLayoutPayload(
                    roles=[
                        UpdateGarageClusterLayoutRolePayload(
                            id=node_id,
                            zone=layout_zone,
                            capacity=layout_capacity,
                        )
                    ]
                ),
                **common,
            )
            current_layout = await self.get_cluster_layout(**common)
            await self.apply_cluster_layout(
                payload=ApplyGarageClusterLayoutPayload(
                    version=current_layout.version + 1
                ),
                **common,
            )

    async def _configure_bucket(
        self,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
        key_name: str,
        bucket_alias: str,
        layout_zone: str,
        layout_capacity: int,
    ) -> GarageBucketCredentials:
        """Provision layout, an access key, a bucket, and permissions for one bucket."""
        common = dict(
            client=client,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
        )

        await self._ensure_layout(
            client=client,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
            layout_zone=layout_zone,
            layout_capacity=layout_capacity,
        )

        # Get-or-create access key (delete+recreate to recover secret key)
        existing_keys = await self.list_keys(**common)
        matching_key = next((k for k in existing_keys if k.name == key_name), None)
        if matching_key is not None:
            await self.delete_key(
                payload=DeleteGarageKeyPayload(accessKeyId=matching_key.accessKeyId),
                **common,
            )
        key = await self.create_key(
            payload=CreateGarageKeyPayload(name=key_name),
            **common,
        )

        # Get-or-create bucket
        existing_buckets = await self.list_buckets(**common)
        matching_bucket = next(
            (b for b in existing_buckets if bucket_alias in b.globalAliases), None
        )
        if matching_bucket is not None:
            bucket_id = matching_bucket.id
        else:
            bucket = await self.create_bucket(
                payload=CreateGarageBucketPayload(globalAlias=bucket_alias),
                **common,
            )
            bucket_id = bucket.id

        # Grant key permissions on bucket (idempotent)
        await self.allow_bucket_key(
            payload=AllowGarageBucketKeyPayload(
                accessKeyId=key.accessKeyId,
                bucketId=bucket_id,
                permissions=GarageBucketKeyPermissions(
                    read=True, write=True, owner=True
                ),
            ),
            **common,
        )

        return GarageBucketCredentials(
            access_key_id=SecretStr(key.accessKeyId),
            secret_access_key=key.secretAccessKey,
            bucket_id=bucket_id,
        )

    async def configure_artifacts(
        self,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
        key_name: str = "aistudio-artifacts-key",
        bucket_alias: str = "aistudio-artifacts",
        layout_zone: str = "dc1",
        layout_capacity: int = 1_073_741_824,
    ) -> GarageBucketCredentials:
        """Provision the model artifacts bucket with its own dedicated access key."""
        return await self._configure_bucket(
            client=client,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
            key_name=key_name,
            bucket_alias=bucket_alias,
            layout_zone=layout_zone,
            layout_capacity=layout_capacity,
        )

    async def configure_datasets(
        self,
        client: httpx.AsyncClient,
        garage_admin_token: SecretStr,
        tapis_token: SecretStr,
        key_name: str = "aistudio-datasets-key",
        bucket_alias: str = "aistudio-datasets",
        layout_zone: str = "dc1",
        layout_capacity: int = 1_073_741_824,
    ) -> GarageBucketCredentials:
        """Provision the datasets bucket with its own dedicated access key."""
        return await self._configure_bucket(
            client=client,
            garage_admin_token=garage_admin_token,
            tapis_token=tapis_token,
            key_name=key_name,
            bucket_alias=bucket_alias,
            layout_zone=layout_zone,
            layout_capacity=layout_capacity,
        )
