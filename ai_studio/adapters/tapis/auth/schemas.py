"""Pydantic models for Tapis authentication responses."""

from pydantic import BaseModel


class TapisUserInfo(BaseModel):
    """Subset of user identity fields returned by Tapis userinfo.

    Attributes:
        username: Authenticated Tapis username.
    """

    username: str


class TapisJWTValidationResponse(BaseModel):
    """Envelope for Tapis token validation responses.

    Attributes:
        result: Parsed user identity payload.
    """

    result: TapisUserInfo
