"""Pydantic schemas for Garage cluster layout payloads and responses."""

from pydantic import BaseModel, Field, SecretStr


class UpdateGarageClusterLayoutRolePayload(BaseModel):
    """Garage layout role settings for a single storage node."""

    id: str
    zone: str
    capacity: int
    tags: list[str] = Field(default_factory=list)


class UpdateGarageClusterLayoutPayload(BaseModel):
    """Payload for staging Garage cluster layout roles."""

    roles: list[UpdateGarageClusterLayoutRolePayload] = Field(default_factory=list)


class GetGarageHealthResponse(BaseModel):
    """Garage health summary returned by the admin API."""

    status: str
    knownNodes: int
    connectedNodes: int
    storageNodes: int
    storageNodesUp: int
    partitions: int
    partitionsQuorum: int
    partitionsAllOk: int


class GarageClusterStatusNodeRole(BaseModel):
    """Role information for a Garage cluster node."""

    zone: str
    tags: list[str] = Field(default_factory=list)
    capacity: int


class GarageClusterStatusNodePartition(BaseModel):
    """Partition availability counts for a Garage node."""

    available: int
    total: int


class GarageClusterStatusNode(BaseModel):
    """Garage cluster node status returned by the admin API."""

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
    """Garage cluster status response with all known nodes."""

    layoutVersion: int
    nodes: list[GarageClusterStatusNode] = Field(default_factory=list)


class GarageClusterLayoutRole(BaseModel):
    """Applied Garage layout role for a storage node."""

    id: str
    zone: str
    tags: list[str] = Field(default_factory=list)
    capacity: int
    storedPartitions: int
    usableCapacity: int


class GarageClusterLayoutParameters(BaseModel):
    """Garage cluster layout parameters."""

    zoneRedundancy: str


class UpdateGarageClusterLayoutResponse(BaseModel):
    """Garage layout response after staging or reading layout changes."""

    version: int
    roles: list[GarageClusterLayoutRole] = Field(default_factory=list)
    parameters: GarageClusterLayoutParameters
    partitionSize: int
    stagedRoleChanges: list[dict] = Field(default_factory=list)
    stagedParameters: dict | None = None


class ApplyGarageClusterLayoutPayload(BaseModel):
    """Payload for applying the currently staged Garage layout version."""

    version: int


class ApplyGarageClusterLayoutResponse(BaseModel):
    """Response returned after applying a staged Garage layout."""

    message: list[str] = Field(default_factory=list)
    layout: UpdateGarageClusterLayoutResponse


class CreateGarageKeyPayload(BaseModel):
    """Payload for creating a Garage access key."""

    name: str


class GarageKeyPermissions(BaseModel):
    """Cluster-level permissions granted to a Garage access key."""

    createBucket: bool = False


class CreateGarageKeyResponse(BaseModel):
    """Garage access key response including the one-time secret key."""

    accessKeyId: str
    created: str
    name: str
    expiration: str | None = None
    expired: bool
    secretAccessKey: SecretStr
    permissions: GarageKeyPermissions
    buckets: list[str] = Field(default_factory=list)


class CreateGarageBucketPayload(BaseModel):
    """Payload for creating a Garage bucket with a global alias."""

    globalAlias: str


class GarageBucketQuotas(BaseModel):
    """Optional quota limits configured on a Garage bucket."""

    maxSize: int | None = None
    maxObjects: int | None = None


class GarageBucketKeyPermissions(BaseModel):
    """Per-bucket permissions granted to a Garage access key."""

    read: bool
    write: bool
    owner: bool


class GarageBucketKeyBinding(BaseModel):
    """Garage bucket binding for an access key and its permissions."""

    accessKeyId: str
    name: str
    permissions: GarageBucketKeyPermissions
    bucketLocalAliases: list[str] = Field(default_factory=list)


class CreateGarageBucketResponse(BaseModel):
    """Garage bucket response including aliases, key bindings, and usage."""

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
    """Payload for granting an access key permissions on a bucket."""

    accessKeyId: str
    bucketId: str
    permissions: GarageBucketKeyPermissions


class AllowGarageBucketKeyResponse(CreateGarageBucketResponse):
    """Response body for Garage AllowBucketKey endpoint."""


class ListGarageKeysResponseItem(BaseModel):
    """Compact Garage access key item returned by list operations."""

    accessKeyId: str
    name: str


class ListGarageBucketsResponseItem(BaseModel):
    """Compact Garage bucket item returned by list operations."""

    id: str
    globalAliases: list[str] = Field(default_factory=list)
    localAliases: list[str] = Field(default_factory=list)


class DeleteGarageKeyPayload(BaseModel):
    """Payload for deleting a Garage access key."""

    accessKeyId: str


class GarageBucketCredentials(BaseModel):
    """Credentials for a single Garage bucket."""

    access_key_id: SecretStr
    secret_access_key: SecretStr
    bucket_id: str
