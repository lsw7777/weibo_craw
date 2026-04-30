from __future__ import annotations

from pathlib import Path

from app.core.config import BACKEND_ROOT, settings
from app.models.schemas import AuthCookieStatus
from app.services.browser_auth import BrowserCookieProvider


COOKIE_KEY = "WEIBO_COOKIE_STRING"


class AuthConfigService:
    def get_status(self) -> AuthCookieStatus:
        configured = bool(settings.cookie_string and settings.cookie_string.strip())
        source = "manual" if configured else "browser"
        try:
            cookies = BrowserCookieProvider().build_playwright_cookies()
        except Exception as exc:
            return AuthCookieStatus(
                configured=configured,
                readable=False,
                source=source if configured else "none",
                cookie_count=0,
                message=str(exc),
            )

        return AuthCookieStatus(
            configured=configured,
            readable=True,
            source=source,
            cookie_count=len(cookies),
            message="已读取微博登录态。",
        )

    def save_cookie_string(self, cookie_string: str) -> AuthCookieStatus:
        normalized = self._normalize_cookie_string(cookie_string)
        settings.cookie_string = normalized
        self._upsert_env_value(BACKEND_ROOT / ".env", COOKIE_KEY, normalized)
        return self.get_status()

    def _normalize_cookie_string(self, cookie_string: str) -> str:
        normalized = cookie_string.strip()
        if "\n" in normalized or "\r" in normalized:
            raise RuntimeError("Cookie 必须是一整行请求头内容，请不要包含换行。")
        if "=" not in normalized or ";" not in normalized:
            raise RuntimeError("Cookie 格式不正确，应类似 SUB=...; XSRF-TOKEN=...; ...")
        return normalized

    def _upsert_env_value(self, env_path: Path, key: str, value: str) -> None:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
        next_line = f'{key}="{escaped_value}"'

        if not env_path.exists():
            env_path.write_text(f"{next_line}\n", encoding="utf-8")
            return

        lines = env_path.read_text(encoding="utf-8").splitlines()
        replaced = False
        updated_lines: list[str] = []
        for line in lines:
            if line.startswith(f"{key}="):
                updated_lines.append(next_line)
                replaced = True
            else:
                updated_lines.append(line)

        if not replaced:
            updated_lines.append(next_line)

        env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
