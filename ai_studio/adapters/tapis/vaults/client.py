"""Client wrapper for reading and writing user secrets through Tapis Vault APIs."""

import httpx
from pydantic import BaseModel, ValidationError

from ai_studio.exceptions import (
    InvalidResponseError,
    ServiceUnavailableError,
    UpstreamServiceError,
)
from ai_studio.adapters.tapis.vaults.schemas import (
    ReadTapisSecretResponse,
    WriteTapisSecret,
    WriteTapisSecretResponse,
)


class TapisVaultClient:
    """Handle secret read/write operations through the Tapis Vault API."""

    async def _make_request[T: BaseModel](
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        token: str,
        response_model: type[T],
        json_data: dict | None = None,
    ) -> T:
        """Send an HTTP request to the Tapis SK API and validate the response."""
        try:
            response = await client.request(
                method=method,
                url=url,
                json=json_data,
                headers={"X-Tapis-Token": token},
            )
            if response.status_code not in (200, 201):
                raise UpstreamServiceError(
                    status_code=response.status_code,
                    detail={
                        "message": "Tapis Vault API returned an error",
                        "details": response.text,
                    },
                )
            return response_model.model_validate(response.json())
        except httpx.RequestError as error:
            raise ServiceUnavailableError(
                status_code=503,
                detail={
                    "message": "Unable to reach Tapis Vault service",
                    "details": f"{type(error).__name__}: {str(error)}",
                },
            )
        except ValidationError as error:
            errors = error.errors()
            error_details = [f"{err['loc'][-1]}: {err['msg']}" for err in errors]
            raise InvalidResponseError(
                status_code=502,
                detail={
                    "message": "Tapis Vault API returned invalid response format",
                    "details": error_details,
                },
            )

    async def read_secret(
        self, secret_id: str, token: str, client: httpx.AsyncClient
    ) -> ReadTapisSecretResponse:
        return await self._make_request(
            client=client,
            method="GET",
            url=f"/v3/security/vault/secret/user/{secret_id}",
            token=token,
            response_model=ReadTapisSecretResponse,
        )

    async def write_secret(
        self,
        secret_id: str,
        secret: WriteTapisSecret,
        token: str,
        client: httpx.AsyncClient,
    ) -> WriteTapisSecretResponse:
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/security/vault/secret/user/{secret_id}",
            token=token,
            response_model=WriteTapisSecretResponse,
            json_data=secret.model_dump(),
        )
