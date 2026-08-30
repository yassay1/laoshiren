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
    redis_url: str = "redis://localhost:6379/0"
    redis_wakeup_enabled: bool = True
    log_level: str = "INFO"
    dev_auth_token: str = Field(default="change-me", repr=False)
    dev_user_id: str = "00000000-0000-0000-0000-000000000001"
    object_storage_path: str = "var/objects"
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    model_provider: str = ""
    model_name: str = "deepseek-v4-flash"
    model_api_base: str = "https://api.deepseek.com"
    model_api_key: str = Field(default="", repr=False)
    model_fallback_provider: str = ""
    model_fallback_name: str = ""
    model_fallback_api_base: str = ""
    model_fallback_api_key: str = Field(default="", repr=False)
    model_timeout_seconds: float = Field(default=60.0, gt=0)
    embedding_model_name: str = ""
    embedding_api_base: str = ""
    embedding_api_key: str = Field(default="", repr=False)
    embedding_dimensions: int = Field(default=1536, gt=0)
    embedding_timeout_seconds: float = Field(default=20.0, gt=0)
    automation_poll_seconds: float = Field(default=30.0, gt=0)
    run_lease_seconds: float = Field(default=60.0, gt=0)
    run_heartbeat_seconds: float = Field(default=15.0, gt=0)
    run_scan_seconds: float = Field(default=2.0, gt=0)
    run_scan_batch_size: int = Field(default=10, gt=0)
    runtime_max_model_steps: int = Field(default=12, gt=0)
    runtime_max_tool_actions: int = Field(default=8, gt=0)
    runtime_max_active_wall_time_seconds: float = Field(default=300.0, gt=0)
    runtime_max_input_tokens: int = Field(default=120_000, gt=0)
    runtime_max_output_tokens: int = Field(default=16_000, gt=0)
    runtime_max_external_actions: int = Field(default=3, gt=0)
    model_retry_attempts: int = Field(default=3, gt=0)
    model_retry_base_seconds: float = Field(default=0.25, ge=0)
    source_poll_seconds: float = Field(default=2.0, gt=0)
    source_batch_size: int = Field(default=10, gt=0)
    source_lease_seconds: float = Field(default=60.0, gt=0)
    source_heartbeat_seconds: float = Field(default=15.0, gt=0)
    source_max_attempts: int = Field(default=3, gt=0)
    source_retry_base_seconds: float = Field(default=5.0, ge=0)
    source_retry_max_seconds: float = Field(default=300.0, gt=0)
    source_parse_timeout_seconds: float = Field(default=30.0, gt=0)
    source_max_extracted_characters: int = Field(default=200_000, gt=0)
    source_max_pdf_pages: int = Field(default=200, gt=0)
    source_max_pdf_page_characters: int = Field(default=20_000, gt=0)
    search_provider: str = "recording"
    search_api_key: str = Field(default="", repr=False)
    search_api_base: str = "https://api.tavily.com"
    search_timeout_seconds: float = Field(default=15.0, gt=0)
    search_default_limit: int = Field(default=5, gt=0)
    search_max_snippet_characters: int = Field(default=8_000, gt=0)
    search_cache_ttl_seconds: int = Field(default=21_600, ge=0)
    search_max_queries_per_run: int = Field(default=6, gt=0)
    parallel_read_max: int = Field(default=4, gt=0)
    session_ttl_hours: int = Field(default=24 * 30, gt=0)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = Field(default=120, gt=0)
    object_storage_backend: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
