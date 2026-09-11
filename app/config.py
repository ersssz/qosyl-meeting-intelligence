from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or the local .env file."""

    mock_llm: bool = True
    allow_mock_fallback: bool = True
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_api_key: str = ""
    analysis_provider: Literal["gemini", "ollama", "mock"] = "gemini"
    transcription_provider: Literal["gemini", "faster-whisper", "mock"] = "gemini"
    airgap_mode: bool = False
    local_llm_base_url: str = "http://127.0.0.1:11434"
    local_llm_model: str = "qwen3:4b"
    local_asr_model: str = "medium"
    local_asr_device: Literal["auto", "cuda", "cpu"] = "auto"
    local_asr_compute_type: str = "int8_float16"
    audio_max_bytes: int = Field(default=30_000_000, ge=1, le=200_000_000)
    llm_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    gemini_rpm_limit: int | None = Field(default=None, ge=1)
    gemini_rpd_limit: int | None = Field(default=None, ge=1)
    quota_rate_limit_cooldown_seconds: int = Field(default=60, ge=1, le=3_600)
    quota_network_cooldown_seconds: int = Field(default=20, ge=1, le=600)
    database_path: Path = Path("data/audit.db")
    api_url: str = "http://127.0.0.1:8000"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    ui_port: int = Field(default=8501, ge=1, le=65535)
    input_max_chars: int = Field(default=50_000, ge=1, le=1_000_000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
