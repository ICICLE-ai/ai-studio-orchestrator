"""Authentication helpers for validating Tapis user tokens."""

import logging

import httpx
from pydantic import SecretStr

from ai_studio.adapters.http import make_request
from ai_studio.exceptions import (
    AuthenticationError,
)
from ai_studio.adapters.tapis.auth.schemas import (
    TapisJWTValidationResponse,
    TapisUserInfo,
)

logger = logging.getLogger("ai_studio.adapters.tapis.auth")


class TapisAuthClient:
    """Utilities for validating bearer tokens against Tapis OAuth APIs."""

    async def validate_token(
        self,
        token: SecretStr,
        client: httpx.AsyncClient,
    ) -> TapisUserInfo:
        """Validate a Tapis token and return the corresponding user payload.

        Args:
            token: Tapis token provided in the ``X-Tapis-Token`` header.
            client: Shared async HTTP client used to reach the auth service.

        Returns:
            Authenticated user information returned by ``/v3/oauth2/userinfo``.

        Raises:
            AuthenticationError: If the auth service rejects the token.
            ServiceUnavailableError: If the auth service cannot be reached.
            InvalidResponseError: If the auth service returns an unparseable response.
        """
        logger.debug("auth.validate_token")
        result = (
            await make_request(
                client=client,
                method="GET",
                url="/v3/oauth2/userinfo",
                headers={"X-Tapis-Token": token.get_secret_value()},
                response_model=TapisJWTValidationResponse,
                upstream_error_message="Authentication service returned an error",
                invalid_response_message="Invalid response from authentication service",
                unavailable_message="Unable to reach authentication service",
                upstream_error_class=AuthenticationError,
            )
        ).result
        logger.info("auth.validate_token.success username=%s", result.username)
        return result
