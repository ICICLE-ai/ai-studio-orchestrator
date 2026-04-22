"""Pydantic schemas for Garage cluster layout payloads and responses."""

from pydantic import BaseModel, Field


class UpdateGarageClusterLayoutRolePayload(BaseModel):
    id: str
    zone: str
    capacity: int
    tags: list[str] = Field(default_factory=list)


class UpdateGarageClusterLayoutPayload(BaseModel):
    roles: list[UpdateGarageClusterLayoutRolePayload] = Field(default_factory=list)


class GetGarageHealthResponse(BaseModel):
    status: str
    knownNodes: int
    connectedNodes: int
    storageNodes: int
    storageNodesUp: int
    partitions: int
    partitionsQuorum: int
    partitionsAllOk: int


class GarageClusterStatusNodeRole(BaseModel):
    zone: str
    tags: list[str] = Field(default_factory=list)
    capacity: int


class GarageClusterStatusNodePartition(BaseModel):
    available: int
    total: int


class GarageClusterStatusNode(BaseModel):
    id: str
    garageVersion: str
    addr: str
    hostname: str
    isUp: bool
    lastSeenSecsAgo: int | None = None
    role: GarageClusterStatusNodeRole
    draining: bool
    dataPartition: GarageClusterStatusNodePartition
    metadataPartition: GarageClusterStatusNodePartition


class GetGarageClusterStatusResponse(BaseModel):
    layoutVersion: int
    nodes: list[GarageClusterStatusNode] = Field(default_factory=list)


class GarageClusterLayoutRole(BaseModel):
    id: str
    zone: str
    tags: list[str] = Field(default_factory=list)
    capacity: int
    storedPartitions: int
    usableCapacity: int


class GarageClusterLayoutParameters(BaseModel):
    zoneRedundancy: str


class UpdateGarageClusterLayoutResponse(BaseModel):
    version: int
    roles: list[GarageClusterLayoutRole] = Field(default_factory=list)
    parameters: GarageClusterLayoutParameters
    partitionSize: int
    stagedRoleChanges: list[dict] = Field(default_factory=list)
    stagedParameters: dict | None = None


class ApplyGarageClusterLayoutPayload(BaseModel):
    version: int


class ApplyGarageClusterLayoutResponse(BaseModel):
    message: list[str] = Field(default_factory=list)
    layout: UpdateGarageClusterLayoutResponse


class CreateGarageKeyPayload(BaseModel):
    name: str


class GarageKeyPermissions(BaseModel):
    createBucket: bool = False


class CreateGarageKeyResponse(BaseModel):
    accessKeyId: str
    created: str
    name: str
    expiration: str | None = None
    expired: bool
    secretAccessKey: str
    permissions: GarageKeyPermissions
    buckets: list[str] = Field(default_factory=list)


class CreateGarageBucketPayload(BaseModel):
    globalAlias: str


class GarageBucketQuotas(BaseModel):
    maxSize: int | None = None
    maxObjects: int | None = None


class GarageBucketKeyPermissions(BaseModel):
    read: bool
    write: bool
    owner: bool


class GarageBucketKeyBinding(BaseModel):
    accessKeyId: str
    name: str
    permissions: GarageBucketKeyPermissions
    bucketLocalAliases: list[str] = Field(default_factory=list)


class CreateGarageBucketResponse(BaseModel):
    id: str
    created: str
    globalAliases: list[str] = Field(default_factory=list)
    websiteAccess: bool
    websiteConfig: dict | None = None
    keys: list[GarageBucketKeyBinding] = Field(default_factory=list)
    objects: int
    bytes: int
    unfinishedUploads: int
    unfinishedMultipartUploads: int
    unfinishedMultipartUploadParts: int
    unfinishedMultipartUploadBytes: int
    quotas: GarageBucketQuotas


class AllowGarageBucketKeyPayload(BaseModel):
    accessKeyId: str
    bucketId: str
    permissions: GarageBucketKeyPermissions


class AllowGarageBucketKeyResponse(CreateGarageBucketResponse):
    """Response body for Garage AllowBucketKey endpoint."""


class ListGarageKeysResponseItem(BaseModel):
    accessKeyId: str
    name: str


class ListGarageBucketsResponseItem(BaseModel):
    id: str
    globalAliases: list[str] = Field(default_factory=list)
    localAliases: list[str] = Field(default_factory=list)


class DeleteGarageKeyPayload(BaseModel):
    accessKeyId: str


class GarageBucketCredentials(BaseModel):
    """Credentials for a single Garage bucket."""

    access_key_id: str
    secret_access_key: str
    bucket_id: str
