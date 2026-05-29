"""Typed settings loaded from .env via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Backend
    backend_base_url: str = Field(default="http://localhost:8000")
    backend_api_prefix: str = Field(default="/api/v1")
    backend_test_mode: bool = Field(default=True)

    # Frontend
    frontend_base_url: str = Field(default="http://localhost:3000")

    # SuperAdmin bootstrap
    superadmin_email: str = Field(default="playwright-super@learningbrix.test")
    superadmin_password: str = Field(default="ChangeMe!2026")
    superadmin_first_name: str = Field(default="Playwright")
    superadmin_other_names: str = Field(default="Super")

    # Browser
    headless: bool = Field(default=False)
    slow_mo_ms: int = Field(default=0)
    default_timeout_ms: int = Field(default=15_000)
    navigation_timeout_ms: int = Field(default=30_000)
    viewport_width: int = Field(default=1440)
    viewport_height: int = Field(default=900)

    # Behavior
    delete_on_failure: bool = Field(default=True)
    feature_scenarios_path: str = Field(default="config/feature_scenarios.yaml")

    @property
    def backend_api_url(self) -> str:
        """Full base URL for backend API calls (with prefix)."""
        return self.backend_base_url.rstrip("/") + self.backend_api_prefix

    @property
    def scenarios_file(self) -> Path:
        p = Path(self.feature_scenarios_path)
        if not p.is_absolute():
            p = ROOT / p
        return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
