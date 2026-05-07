"""Pydantic models for Tapis Vault secret read and write operations."""

from pydantic import BaseModel, Field


class WriteTapisSecret(BaseModel):
    """Payload used to create or update a user secret in Tapis Vault."""

    tenant: str
    user: str
    data: dict[str, str] = Field(default_factory=dict)


class TapisSecretMetadata(BaseModel):
    """Metadata returned for a specific stored secret version."""

    created_time: str
    deletion_time: str
    destroyed: bool
    version: int


class TapisSecret(BaseModel):
    """Secret object containing key-value data plus version metadata."""

    secretMap: dict[str, str]
    metadata: TapisSecretMetadata


class ReadTapisSecretResponse(BaseModel):
    """Tapis API envelope for a single vault secret read response."""

    build: str
    commit: str
    message: str
    metadata: dict
    result: TapisSecret
    status: str
    version: str


class WriteTapisSecretResponse(BaseModel):
    """Tapis API envelope for a vault secret write response."""

    build: str
    commit: str
    message: str
    metadata: dict
    result: TapisSecretMetadata
    status: str
    version: str
