"""Schemas for studio lifecycle endpoints."""

from pydantic import BaseModel


class StudioResponse[T](BaseModel):
    """Standard response envelope for studio lifecycle endpoints."""

    status: int
    version: int
    message: str
    result: T


class StudioLifecycleResult(BaseModel):
    """Summary of lifecycle actions applied to studio resources."""

    username: str
    changed: list[str]
    skipped: list[str]
