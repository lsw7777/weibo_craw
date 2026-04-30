from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.models.schemas import ScrapeAccountsConfig


class ScrapeConfigService:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.data_dir / "scrape_accounts.json"

    def load_accounts(self) -> ScrapeAccountsConfig:
        if not self.path.exists():
            return ScrapeAccountsConfig()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"本地账号配置文件格式损坏: {self.path}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"本地账号配置文件格式不正确: {self.path}")

        return ScrapeAccountsConfig(
            accounts=self._normalize_accounts(payload.get("accounts", [])),
            updated_at=payload.get("updated_at"),
        )

    def save_accounts(self, payload: ScrapeAccountsConfig) -> ScrapeAccountsConfig:
        saved = ScrapeAccountsConfig(
            accounts=self._normalize_accounts(payload.accounts),
            updated_at=datetime.now(timezone.utc),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(
                {
                    "accounts": saved.accounts,
                    "updated_at": saved.updated_at.isoformat() if saved.updated_at else None,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)
        return saved

    def _normalize_accounts(self, accounts: list[str]) -> list[str]:
        if not isinstance(accounts, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for account in accounts:
            value = str(account).strip()
            if not value or value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        return normalized
