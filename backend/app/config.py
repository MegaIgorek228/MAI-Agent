from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MAI-Agent Backend"
    app_env: str = "development"
    database_url: str = Field(
        default="postgresql+psycopg://mai_agent:change_me@localhost:5432/mai_agent"
    )
    jwt_secret_key: str = Field(default="change_me_in_local_environment")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    acp_transport: str = "stdio"
    hermes_command: str = "hermes-acp"
    hermes_cwd: str = "."
    acp_startup_timeout_seconds: int = 60
    acp_prompt_timeout_seconds: int = 600
    hermes_max_processes: int = Field(default=8, ge=1)
    hermes_idle_timeout_seconds: int = Field(default=900, ge=1)
    mcp_public_url: str = "http://localhost:8000/mcp"
    llm_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("LLM_BASE_URL", "QWEN_BASE_URL")
    )
    llm_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("LLM_API_KEY", "QWEN_API_KEY")
    )
    document_model: str | None = Field(
        default=None, validation_alias=AliasChoices("DOCUMENT_MODEL", "QWEN_MODEL")
    )
    ai_api_ca_bundle: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = "bge-m3"
    max_upload_size_bytes: int = 10 * 1024 * 1024
    max_image_size_bytes: int = 10 * 1024 * 1024
    embedding_dimensions: int = 1024
    official_source_domains: str = "mai.ru,priem.mai.ru"
    official_source_root_urls: str = "https://mai.ru,https://priem.mai.ru"
    telegram_bot_token: str | None = None
    telegram_polling_timeout_seconds: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
