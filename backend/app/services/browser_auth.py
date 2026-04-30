from __future__ import annotations

import os
import shutil
import tempfile
from http.cookiejar import Cookie
from pathlib import Path

import browser_cookie3
import requests
from requests.cookies import RequestsCookieJar

from app.core.config import settings


class BrowserCookieProvider:
    def __init__(self, browser_name: str | None = None) -> None:
        self.browser_name = (browser_name or settings.cookie_browser).lower()

    def _read_cookie_jar(self):
        if settings.cookie_string and settings.cookie_string.strip():
            return self._jar_from_cookie_string(settings.cookie_string)

        source = self._resolve_cookie_file()
        temp_dir = Path(tempfile.mkdtemp(prefix="weibo-cookie-"))
        cookie_file = temp_dir / "Cookies"
        try:
            shutil.copy2(source, cookie_file)
        except PermissionError as exc:
            raise RuntimeError(
                "浏览器 Cookie 数据库已被 Edge/Chrome 或 Windows 锁定，后端普通进程无法直接读取。"
            ) from exc
        try:
            if self.browser_name == "edge":
                return browser_cookie3.edge(cookie_file=str(cookie_file), domain_name="weibo.com")
            if self.browser_name == "chrome":
                return browser_cookie3.chrome(cookie_file=str(cookie_file), domain_name="weibo.com")
            raise RuntimeError(f"暂不支持的浏览器类型: {self.browser_name}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _resolve_cookie_file(self) -> Path:
        if settings.browser_cookie_file:
            candidate = Path(settings.browser_cookie_file)
            if candidate.exists():
                return candidate
            raise RuntimeError(f"指定的浏览器 Cookie 文件不存在: {candidate}")

        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("未找到 LOCALAPPDATA 环境变量，无法定位浏览器 Cookie 文件。")

        if self.browser_name == "edge":
            user_data_dir = Path(local_app_data) / "Microsoft" / "Edge" / "User Data"
        elif self.browser_name == "chrome":
            user_data_dir = Path(local_app_data) / "Google" / "Chrome" / "User Data"
        else:
            raise RuntimeError(f"暂不支持的浏览器类型: {self.browser_name}")

        profile_name = settings.browser_profile
        candidates = [
            user_data_dir / profile_name / "Network" / "Cookies",
            user_data_dir / profile_name / "Cookies",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise RuntimeError(
            "未找到浏览器 Cookie 数据库，请确认浏览器类型、Profile 名称和登录状态是否正确。"
        )

    def _jar_from_cookie_string(self, cookie_string: str) -> RequestsCookieJar:
        jar = RequestsCookieJar()
        parts = [item.strip() for item in cookie_string.split(";") if item.strip()]
        for part in parts:
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            jar.set(name.strip(), value.strip(), domain=".weibo.com", path="/")
        if not jar:
            raise RuntimeError("WEIBO_COOKIE_STRING 已配置，但未解析出任何有效 Cookie。")
        return jar

    def build_requests_session(self) -> requests.Session:
        try:
            jar = self._read_cookie_jar()
        except Exception as exc:
            raise RuntimeError(
                f"读取微博登录态失败：{exc} 可先确认 Edge/Chrome 已登录微博；若当前 Windows 无法直接读取浏览器 Cookie，"
                "请在前端登录态设置中保存微博请求 Cookie。"
            ) from exc

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": settings.api_user_agent,
                "Referer": "https://weibo.com/",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        session.cookies.update(jar)
        return session

    def build_playwright_cookies(self) -> list[dict]:
        try:
            jar = self._read_cookie_jar()
        except Exception as exc:
            raise RuntimeError(
                f"读取微博登录态失败：{exc} 请确认浏览器已登录，或在前端登录态设置中保存微博请求 Cookie。"
            ) from exc

        cookies: list[dict] = []
        for item in jar:
            if not isinstance(item, Cookie):
                continue
            cookie_payload = {
                "name": item.name,
                "value": item.value,
                "domain": item.domain or ".weibo.com",
                "path": item.path or "/",
                "httpOnly": bool(item._rest.get("HttpOnly")),  # noqa: SLF001
                "secure": bool(item.secure),
            }
            if item.expires and item.expires > 0:
                cookie_payload["expires"] = item.expires
            cookies.append(cookie_payload)
        return cookies
