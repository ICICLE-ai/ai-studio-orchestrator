"""Pydantic schemas for Tapis pod snapshot resources and responses."""

from pydantic import BaseModel

from ai_studio.adapters.tapis.pods.validators import CronString, PositivePowerOfTwo


class CreateTapisPodVolumeSnapshot(BaseModel):
    """Pydantic schema for creating a Tapis Pod Volume Snapshot."""

    snapshot_id: str
    source_volume_id: str
    source_volume_path: str
    destination_path: str = ""
    description: str = ""
    size_limit: PositivePowerOfTwo = 1024
    cron: CronString = ""
    retention_policy: str = ""


class TapisPodVolumeSnapshot(BaseModel):
    """Response model for a Tapis Pod Volume Snapshot resource."""

    snapshot_id: str
    source_volume_id: str = ""
    source_volume_path: str = ""
    destination_path: str = ""
    description: str = ""
    size_limit: int = 1024
    size: int = 0
    cron: str = ""
    retention_policy: str = ""
    status: str = "REQUESTED"
    creation_ts: str | None = None
    update_ts: str | None = None


class TapisPodVolumeSnapshotApiResponse(BaseModel):
    """Tapis API envelope for a single snapshot response."""

    message: str
    metadata: dict[str, str]
    result: TapisPodVolumeSnapshot
    status: str
    version: str
