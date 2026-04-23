"""Application configuration models and environment-backed settings."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# class DatabaseSettings(BaseSettings):
#     user: str
#     password: str
#     host: str
#     port: int
#     database: str
#     echo: bool = False
#     pool_size: int = 20
#     max_overflow: int = 20
#     pool_recycle: int = 3600
#
#     class Config:
#         env_file: str = ".env"
#         env_prefix = "DB_"
#         extra = "ignore"
#


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


# class TapisVaultSettings(BaseSettings):
#     vault_url: str
#     tapis_tenant: str
#     tapis_user: str
#     tapis_token: str
#
#     class Config:
#         env_file: str = ".env"
#         extra = "ignore"
#

# db_config = DatabaseSettings()
tapis_config = TapisSettings()
# vault_config = TapisVaultSettings()
