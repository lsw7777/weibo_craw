from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DATA_ROOT = BACKEND_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_name: str = "Weibo Craw"
    api_prefix: str = "/api"
    cookie_browser: str = Field(default="edge", alias="WEIBO_COOKIE_BROWSER")
    browser_profile: str = Field(default="Default", alias="WEIBO_BROWSER_PROFILE")
    browser_cookie_file: str | None = Field(default=None, alias="WEIBO_BROWSER_COOKIE_FILE")
    cookie_string: str | None = Field(default=None, alias="WEIBO_COOKIE_STRING")
    playwright_headless: bool = Field(default=True, alias="WEIBO_PLAYWRIGHT_HEADLESS")
    request_timeout: int = Field(default=30, alias="WEIBO_REQUEST_TIMEOUT")
    request_interval_seconds: float = Field(default=0.6, alias="WEIBO_REQUEST_INTERVAL_SECONDS")
    max_page_count: int = Field(default=30, alias="WEIBO_MAX_PAGE_COUNT")
    frontend_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    data_dir: Path = DATA_ROOT
    download_dir: Path = DATA_ROOT / "downloads"
    export_dir: Path = DATA_ROOT / "exports"
    analysis_top_k: int = 8
    analysis_viewpoint_count: int = 5
    api_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
