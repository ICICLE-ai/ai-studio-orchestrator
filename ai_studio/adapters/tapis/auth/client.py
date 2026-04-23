"""Authentication helpers for validating Tapis user tokens."""

import httpx
from pydantic import SecretStr, ValidationError

from ai_studio.core import tapis_config
from ai_studio.exceptions import (
    AuthenticationError,
    InvalidResponseError,
    ServiceUnavailableError,
)
from ai_studio.adapters.tapis.auth.schemas import (
    TapisJWTValidationResponse,
    TapisUserInfo,
)


class TapisAuthClient:
    """Utilities for validating bearer tokens against Tapis OAuth APIs."""

    async def validate_token(self, token: SecretStr) -> TapisUserInfo:
        """Validate a Tapis token and return the corresponding user payload.

        Args:
            token: Tapis token provided in the ``X-Tapis-Token`` header.

        Returns:
            Authenticated user information returned by ``/v3/oauth2/userinfo``.

        Raises:
            AuthenticationError: If the auth service rejects the token.
            ServiceUnavailableError: If the auth service cannot be reached.
            InvalidResponseError: If the auth service returns an unparseable response.
        """
        async with httpx.AsyncClient(
            base_url=tapis_config.base_url,
            headers={"X-Tapis-Token": token.get_secret_value()},
        ) as client:
            try:
                response: httpx.Response = await client.get(url="/v3/oauth2/userinfo")
                if response.status_code != 200:
                    raise AuthenticationError(
                        status_code=response.status_code,
                        detail={
                            "message": "Authentication service returned an error",
                            "details": response.text,
                        },
                    )
                return TapisJWTValidationResponse.model_validate(response.json()).result
            except httpx.RequestError as error:
                raise ServiceUnavailableError(
                    status_code=503,
                    detail={
                        "message": "Unable to reach authentication service",
                        "details": f"{type(error).__name__}: {str(error)}",
                    },
                )
            except ValidationError as error:
                errors = error.errors()
                error_details = [f"{err['loc'][-1]}: {err['msg']}" for err in errors]
                raise InvalidResponseError(
                    status_code=502,
                    detail={
                        "message": "Invalid response from authentication service",
                        "details": error_details,
                    },
                )
