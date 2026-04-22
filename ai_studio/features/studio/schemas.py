"""Schemas for studio lifecycle endpoints."""

from pydantic import BaseModel

from ai_studio.adapters.tapis.auth import schemas as auth_schemas


class StudioResponse(BaseModel):
    """Standard response envelope for studio lifecycle endpoints."""

    status: int
    version: int
    message: str
    result: auth_schemas.TapisUserInfo
