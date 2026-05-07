"""Pydantic schemas for Tapis pod volume resources and responses."""

from pydantic import BaseModel

from ai_studio_orchestrator.adapters.tapis.pods.validators import PositivePowerOfTwo


class TapisPodVolume(BaseModel):
    """Response model for a Tapis Pod Volume resource."""

    volume_id: str
    description: str = ""
    size_limit: int = 1024
    size: int = 0
    status: str = "REQUESTED"
    creation_ts: str | None = None
    update_ts: str | None = None


class CreateTapisPodVolume(BaseModel):
    """Pydantic schema for creating a Tapis Pod Volume."""

    volume_id: str
    description: str = ""
    size_limit: PositivePowerOfTwo = 1024


class TapisPodVolumeApiResponse(BaseModel):
    """Tapis API envelope for a single volume response."""

    message: str
    metadata: dict[str, str]
    result: TapisPodVolume
    status: str
    version: str
