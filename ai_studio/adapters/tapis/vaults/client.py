"""Client for reading and writing user secrets through Tapis Vault APIs."""

import logging

import httpx
from pydantic import SecretStr

from ai_studio.adapters.http import make_request
from ai_studio.adapters.tapis.vaults.schemas import (
    ReadTapisSecretResponse,
    WriteTapisSecret,
    WriteTapisSecretResponse,
)

logger = logging.getLogger("ai_studio.adapters.tapis.vault")


class TapisVaultClient:
    """Handle secret read/write operations through the Tapis Vault API."""

    async def _make_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        token: SecretStr,
        response_model,
        json_data: dict | None = None,
    ):
        """Send an HTTP request to the Tapis SK API and validate the response."""
        return await make_request(
            client=client,
            method=method,
            url=url,
            json_data=json_data,
            headers={"X-Tapis-Token": token.get_secret_value()},
            response_model=response_model,
            upstream_error_message="Tapis Vault API returned an error",
            invalid_response_message="Tapis Vault API returned invalid response format",
            unavailable_message="Unable to reach Tapis Vault service",
        )

    async def read_secret(
        self, secret_id: str, token: SecretStr, client: httpx.AsyncClient
    ) -> ReadTapisSecretResponse:
        """Read a user-scoped secret from Tapis Vault."""
        logger.debug("vault.read_secret secret_id=%s", secret_id)
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
        token: SecretStr,
        client: httpx.AsyncClient,
    ) -> WriteTapisSecretResponse:
        """Write or replace a user-scoped secret in Tapis Vault."""
        logger.info("vault.write_secret secret_id=%s", secret_id)
        return await self._make_request(
            client=client,
            method="POST",
            url=f"/v3/security/vault/secret/user/{secret_id}",
            token=token,
            response_model=WriteTapisSecretResponse,
            json_data=secret.model_dump(),
        )
