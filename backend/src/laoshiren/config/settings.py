from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "laoshiren-backend"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://laoshiren:laoshiren@localhost:5432/laoshiren"
    log_level: str = "INFO"
    dev_auth_token: str = Field(default="change-me", repr=False)
    dev_user_id: str = "00000000-0000-0000-0000-000000000001"
    object_storage_path: str = "var/objects"
    max_upload_bytes: int = 25 * 1024 * 1024
    model_provider: str = ""
    model_name: str = "deepseek-v4-flash"
    model_api_base: str = "https://api.deepseek.com"
    model_api_key: str = Field(default="", repr=False)
    model_timeout_seconds: float = 60.0
    embedding_model_name: str = ""
    embedding_api_base: str = ""
    embedding_api_key: str = Field(default="", repr=False)
    embedding_dimensions: int = 1536
    embedding_timeout_seconds: float = 20.0
    automation_poll_seconds: float = 30.0
    run_lease_seconds: float = 60.0
    run_heartbeat_seconds: float = 15.0
    run_scan_seconds: float = 2.0
    run_scan_batch_size: int = 500
    source_poll_seconds: float = 2.0
    source_batch_size: int = 10
    source_lease_seconds: float = 60.0
    source_heartbeat_seconds: float = 15.0
    source_max_attempts: int = 3
    source_retry_base_seconds: float = 5.0
    source_retry_max_seconds: float = 300.0
    source_parse_timeout_seconds: float = 30.0
    source_max_extracted_characters: int = 200_000
    source_max_pdf_pages: int = 200
    source_max_pdf_page_characters: int = 20_000
    search_provider: str = "recording"
    search_api_key: str = Field(default="", repr=False)
    search_api_base: str = "https://api.tavily.com"
    search_timeout_seconds: float = 15.0
    search_default_limit: int = 5
    search_max_snippet_characters: int = 8_000
    search_cache_ttl_seconds: int = 21_600
    search_max_queries_per_run: int = 6
    parallel_read_max: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
