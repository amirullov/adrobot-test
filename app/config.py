from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./adrobot.db"

    keitaro_mode: Literal["fake", "http"] = "fake"
    keitaro_base_url: str = "https://tracker.example.com"
    keitaro_api_key: SecretStr = Field(default=SecretStr(""), repr=False)
    keitaro_domain_id: int = 1
    keitaro_group_id: int = 1
    keitaro_traffic_source_id: int = 1
    keitaro_google_url: str = "https://www.google.com/"
    keitaro_admin_campaign_url_template: str = (
        "{base_url}/admin/#!/campaigns/{campaign_id}"
    )
    keitaro_timeout_seconds: float = 10.0
    keitaro_get_retries: int = 2

    keitaro_country_filter_name: str = "country"
    keitaro_redirect_action_type: str = "http"
    keitaro_offer_action_type: str = "http"

    @field_validator("keitaro_base_url")
    @classmethod
    def strip_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("keitaro_api_key")
    @classmethod
    def require_key_in_http_mode(cls, value: SecretStr, info: object) -> SecretStr:
        return value

    def validate_runtime(self) -> None:
        if self.keitaro_mode == "http" and not self.keitaro_api_key.get_secret_value():
            raise ValueError("KEITARO_API_KEY is required when KEITARO_MODE=http")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime()
    return settings
