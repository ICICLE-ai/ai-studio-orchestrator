"""Application configuration models and environment-backed settings."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TapisSettings(BaseSettings):
    """Settings required to authenticate and call Tapis APIs.

    Attributes:
        admin_token: Service or admin token used for privileged Tapis calls.
        base_url: Base URL for Tapis API requests.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="TAPIS_", extra="ignore"
    )

    admin_token: SecretStr
    base_url: str
    tenant: str
    garage_image: str = "dxflrs/garage:090dbb412aff0afcbd42183ec12fa62c15bde58b"
    postgres_template: str = "postgres:16@2024-12-04-18:28:04"
    mlflow_image: str = "ghcr.io/mlflow/mlflow"
    datasets_image: str = "ghcr.io/icicle-ai/ai-studio-datasets:latest"
    traefik_public_host: str = "aistudio.pods.icicleai.tapis.io"
    traefik_dynamic_dir: Path = Path("/shared/traefik/users")

tapis_config = TapisSettings()
