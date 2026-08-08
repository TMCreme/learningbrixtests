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
    # Flag file, relative to the backend repo root, that turns QA mode on.
    backend_qa_flag_file: str = Field(default=".qa_mode_enabled")

    # Frontend
    frontend_base_url: str = Field(default="http://localhost:3000")

    # SuperAdmin bootstrap
    superadmin_email: str = Field(default="playwright-super@learningbrix.test")
    superadmin_password: str = Field(default="ChangeMe!2026")
    superadmin_first_name: str = Field(default="Playwright")
    superadmin_other_names: str = Field(default="Super")

    # Docker container running the backend. The backend refuses SuperAdmin
    # self-registration, so the seed runs the app's own code inside this
    # container. Empty → seeding is skipped.
    backend_container: str = Field(default="")

    # Domain for all generated test emails. The backend's email validator
    # rejects reserved TLDs (.test/.example/.invalid) with a 422.
    test_email_domain: str = Field(default="learningbrix-qa.com")

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

    # Demo video recording
    video_enabled: bool = Field(default=True)
    video_slow_mo_ms: int = Field(default=400)
    video_width: int = Field(default=1280)
    video_height: int = Field(default=720)
    video_max_seconds: int = Field(default=90)
    video_raw_dir: str = Field(default="artifacts/videos/raw")
    video_out_dir: str = Field(default="artifacts/videos/out")

    # Local app repos under test (agents may patch these; never commit)
    backend_repo_path: str = Field(default="")
    frontend_repo_path: str = Field(default="")
    backend_start_cmd: str = Field(default="uvicorn app:app --reload --port 8093")
    frontend_start_cmd: str = Field(default="npm run dev")

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
