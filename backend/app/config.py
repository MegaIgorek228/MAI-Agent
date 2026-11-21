from functools import lru_cache

from pydantic import Field
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
    mcp_public_url: str = "http://localhost:8000/mcp"
    qwen_base_url: str | None = None
    qwen_api_key: str | None = None
    qwen_model: str | None = None
    ai_api_ca_bundle: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
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
