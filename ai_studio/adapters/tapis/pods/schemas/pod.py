"""Pydantic schemas for Tapis pod resources and pod API envelopes."""

from enum import StrEnum, auto
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class TapisPodStatus(StrEnum):
    """Requested lifecycle state of a Tapis pod."""

    ON = auto()
    OFF = auto()
    RESTART = auto()


class TapisNetworkingProtocol(StrEnum):
    """Network protocol for a pod port."""

    http = auto()
    tcp = auto()
    postgres = auto()
    local_only = auto()


class TapisVolumeMount(BaseModel):
    """Configuration for attaching a volume, snapshot, or inline config to a pod."""

    type: Literal["tapisvolume", "tapissnapshot", "ephemeral", "pvc"]
    source_id: str | None = None
    sub_path: str = ""
    read_only: bool | None = None
    config_content: str | None = None
    config_permissions: str = "0644"
    config_filename: str | None = None
    config_update_mode: str = "always"


class TapisNetworking(BaseModel):
    """Networking configuration for a single pod port."""

    protocol: TapisNetworkingProtocol = TapisNetworkingProtocol.http
    port: int = 5000
    url: str = ""
    ip_allow_list: list[str] = Field(default_factory=list)
    tapis_auth: bool = False
    tapis_auth_response_headers: dict[str, str] = Field(default_factory=dict)
    tapis_auth_allowed_users: list[str] = Field(default_factory=lambda: ["*"])
    tapis_auth_return_path: str = "/"
    cors_allow_origins: list[str] = Field(default_factory=list)
    cors_allow_methods: list[str] = Field(default_factory=list)
    cors_allow_headers: list[str] = Field(default_factory=list)
    cors_allow_credentials: bool = False
    cors_max_age: int = 100


class TapisResources(BaseModel):
    """CPU, memory, and GPU resource requests and limits for a pod."""

    cpu_request: int = 250
    cpu_limit: int = 2000
    mem_request: int = 256
    mem_limit: int = 3072
    gpus: int = 0


class CreateTapisPod(BaseModel):
    """Pydantic schema for creating a Tapis Pod."""

    pod_id: str
    image: str = ""
    template: str = ""
    description: str = ""
    command: list[str] | None = None
    arguments: list[str] | None = None
    environment_variables: dict = Field(default_factory=dict)
    secret_map: dict[str, str] = Field(default_factory=dict)
    status_requested: TapisPodStatus = TapisPodStatus.ON
    volume_mounts: dict[str, TapisVolumeMount | None] = Field(default_factory=dict)
    time_to_stop_default: int = 43200
    time_to_stop_instance: int | None = None
    networking: dict[str, TapisNetworking] = Field(
        default_factory=lambda: {
            "default": TapisNetworking(protocol=TapisNetworkingProtocol.http, port=5000)
        }
    )
    resources: TapisResources = Field(default_factory=TapisResources)
    compute_queue: str = "default"
    template_overrides: dict | None = None


class TapisPod(BaseModel):
    """Response model for a Tapis Pod resource."""

    pod_id: str
    image: str = ""
    template: str = ""
    description: str = ""
    command: list[str] | None = None
    arguments: list[str] | None = None
    environment_variables: dict = Field(default_factory=dict)
    secret_map: dict[str, str] = Field(default_factory=dict)
    status_requested: str = "ON"
    status: str = "STOPPED"
    status_container: dict = Field(default_factory=dict)
    volume_mounts: dict = Field(default_factory=dict)
    time_to_stop_default: int = 43200
    time_to_stop_instance: int | None = None
    time_to_stop_ts: str | None = None
    compute_queue: str = "default"
    creation_ts: str | None = None
    update_ts: str | None = None
    start_instance_ts: str | None = None


class TapisPodApiResponse(BaseModel):
    """Tapis API envelope for a single pod response."""

    message: str
    metadata: dict[str, str]
    result: TapisPod
    status: str
    version: str


class TapisPodCredentials(BaseModel):
    """Auto-generated credentials for a template-based Tapis pod."""

    user_username: str
    user_password: SecretStr


class TapisPodCredentialsApiResponse(BaseModel):
    """Tapis API envelope for pod credentials."""

    message: str
    metadata: dict[str, str]
    result: TapisPodCredentials
    status: str
    version: str
