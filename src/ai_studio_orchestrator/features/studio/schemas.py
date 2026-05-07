"""Schemas for studio lifecycle endpoints."""

from typing import Literal

from typing import Self

from pydantic import BaseModel, Field, model_validator

from ai_studio_orchestrator.adapters.tapis.pods.validators import PositivePowerOfTwo


StudioProvisionProfile = Literal["small", "standard", "large", "custom"]


class StudioVolumeOptions(BaseModel):
    """User-selectable Tapis volume options."""

    size_limit: PositivePowerOfTwo = Field(default=1024, ge=256, le=8192)


class StudioVolumeSetOptions(BaseModel):
    """User-selectable volume options for the provisioned studio stack."""

    garage: StudioVolumeOptions | None = None
    postgres: StudioVolumeOptions | None = None
    mlflow_pip_cache: StudioVolumeOptions | None = None


class StudioPodResourceOptions(BaseModel):
    """User-selectable pod resource options."""

    cpu_request: int = Field(default=250, ge=50, le=8000)
    cpu_limit: int = Field(default=2000, ge=50, le=16000)
    mem_request: int = Field(default=256, ge=128, le=32768)
    mem_limit: int = Field(default=3072, ge=128, le=65536)
    gpus: int = Field(default=0, ge=0, le=4)

    @model_validator(mode="after")
    def requests_must_not_exceed_limits(self) -> Self:
        if self.cpu_request > self.cpu_limit:
            raise ValueError("cpu_request must be less than or equal to cpu_limit")
        if self.mem_request > self.mem_limit:
            raise ValueError("mem_request must be less than or equal to mem_limit")
        return self


class StudioResourceSetOptions(BaseModel):
    """User-selectable resource options for user-facing pods."""

    mlflow: StudioPodResourceOptions | None = None
    datasets: StudioPodResourceOptions | None = None


class StudioLifecycleOptions(BaseModel):
    """User-selectable lifecycle options."""

    time_to_stop_default: int = Field(default=43200, ge=3600, le=604800)


class StudioProvisionRequest(BaseModel):
    """Provisioning choices submitted by a frontend."""

    profile: StudioProvisionProfile = "standard"
    volumes: StudioVolumeSetOptions | None = None
    resources: StudioResourceSetOptions | None = None
    lifecycle: StudioLifecycleOptions | None = None


class StudioResolvedVolumeSetOptions(BaseModel):
    """Concrete volume options after profile/default resolution."""

    garage: StudioVolumeOptions
    postgres: StudioVolumeOptions
    mlflow_pip_cache: StudioVolumeOptions


class StudioResolvedResourceSetOptions(BaseModel):
    """Concrete resource options after profile/default resolution."""

    mlflow: StudioPodResourceOptions
    datasets: StudioPodResourceOptions


class StudioProvisionConfig(BaseModel):
    """Concrete provisioning config used by the orchestration service."""

    profile: StudioProvisionProfile
    volumes: StudioResolvedVolumeSetOptions
    resources: StudioResolvedResourceSetOptions
    lifecycle: StudioLifecycleOptions


class StudioProvisionProfileOption(BaseModel):
    """Provisioning profile exposed to frontend clients."""

    id: StudioProvisionProfile
    label: str
    defaults: StudioProvisionConfig


class StudioProvisionConstraints(BaseModel):
    """Validation constraints exposed to frontend clients."""

    volume_size_limit_values: list[int]
    volume_size_unit: str
    cpu_unit: str
    memory_unit: str
    time_to_stop_unit: str


class StudioProvisionOptionsResponse(BaseModel):
    """Available provisioning options for frontend clients."""

    profiles: list[StudioProvisionProfileOption]
    constraints: StudioProvisionConstraints


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


_PROFILE_CONFIGS = {
    "small": StudioProvisionConfig(
        profile="small",
        volumes=StudioResolvedVolumeSetOptions(
            garage=StudioVolumeOptions(size_limit=512),
            postgres=StudioVolumeOptions(size_limit=512),
            mlflow_pip_cache=StudioVolumeOptions(size_limit=512),
        ),
        resources=StudioResolvedResourceSetOptions(
            mlflow=StudioPodResourceOptions(
                cpu_request=250,
                cpu_limit=1000,
                mem_request=256,
                mem_limit=2048,
            ),
            datasets=StudioPodResourceOptions(
                cpu_request=250,
                cpu_limit=1000,
                mem_request=256,
                mem_limit=2048,
            ),
        ),
        lifecycle=StudioLifecycleOptions(time_to_stop_default=21600),
    ),
    "standard": StudioProvisionConfig(
        profile="standard",
        volumes=StudioResolvedVolumeSetOptions(
            garage=StudioVolumeOptions(size_limit=1024),
            postgres=StudioVolumeOptions(size_limit=1024),
            mlflow_pip_cache=StudioVolumeOptions(size_limit=1024),
        ),
        resources=StudioResolvedResourceSetOptions(
            mlflow=StudioPodResourceOptions(),
            datasets=StudioPodResourceOptions(),
        ),
        lifecycle=StudioLifecycleOptions(),
    ),
    "large": StudioProvisionConfig(
        profile="large",
        volumes=StudioResolvedVolumeSetOptions(
            garage=StudioVolumeOptions(size_limit=4096),
            postgres=StudioVolumeOptions(size_limit=2048),
            mlflow_pip_cache=StudioVolumeOptions(size_limit=2048),
        ),
        resources=StudioResolvedResourceSetOptions(
            mlflow=StudioPodResourceOptions(
                cpu_request=500,
                cpu_limit=4000,
                mem_request=1024,
                mem_limit=8192,
            ),
            datasets=StudioPodResourceOptions(
                cpu_request=500,
                cpu_limit=4000,
                mem_request=1024,
                mem_limit=8192,
            ),
        ),
        lifecycle=StudioLifecycleOptions(time_to_stop_default=86400),
    ),
}


def resolve_studio_provision_config(
    request: StudioProvisionRequest | None = None,
) -> StudioProvisionConfig:
    """Resolve a partial frontend request into a concrete provisioning config."""

    request = request or StudioProvisionRequest()
    # Custom requests use standard as the fallback template, then overlay only
    # the fields the client provided. The resolved config still records
    # profile="custom" below.
    base_profile = "standard" if request.profile == "custom" else request.profile
    config = _PROFILE_CONFIGS[base_profile].model_copy(deep=True)
    config.profile = request.profile

    if request.volumes is not None:
        if request.volumes.garage is not None:
            config.volumes.garage = request.volumes.garage
        if request.volumes.postgres is not None:
            config.volumes.postgres = request.volumes.postgres
        if request.volumes.mlflow_pip_cache is not None:
            config.volumes.mlflow_pip_cache = request.volumes.mlflow_pip_cache

    if request.resources is not None:
        if request.resources.mlflow is not None:
            config.resources.mlflow = request.resources.mlflow
        if request.resources.datasets is not None:
            config.resources.datasets = request.resources.datasets

    if request.lifecycle is not None:
        config.lifecycle = request.lifecycle

    return config


def get_studio_provision_options() -> StudioProvisionOptionsResponse:
    """Return provisioning options and constraints for frontend clients."""

    return StudioProvisionOptionsResponse(
        profiles=[
            StudioProvisionProfileOption(
                id="small",
                label="Small",
                defaults=_PROFILE_CONFIGS["small"],
            ),
            StudioProvisionProfileOption(
                id="standard",
                label="Standard",
                defaults=_PROFILE_CONFIGS["standard"],
            ),
            StudioProvisionProfileOption(
                id="large",
                label="Large",
                defaults=_PROFILE_CONFIGS["large"],
            ),
        ],
        constraints=StudioProvisionConstraints(
            volume_size_limit_values=[256, 512, 1024, 2048, 4096, 8192],
            volume_size_unit="tapis_size_limit",
            cpu_unit="millicores",
            memory_unit="MiB",
            time_to_stop_unit="seconds",
        ),
    )
