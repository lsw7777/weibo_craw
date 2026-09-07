from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from http.cookiejar import Cookie
from pathlib import Path

import browser_cookie3
import requests
from requests.cookies import RequestsCookieJar

from app.core.config import settings


WEIBO_HOME_URL = "https://weibo.com/"
UID_PATTERNS = [
    re.compile(r"\$CONFIG\[['\"]uid['\"]\]\s*=\s*['\"]?(\d+)"),
    re.compile(r"[\"']uid[\"']\s*:\s*[\"']?(\d{5,})"),
]
NICK_PATTERNS = [
    re.compile(r"\$CONFIG\[['\"]nick['\"]\]\s*=\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"[\"']screen_name[\"']\s*:\s*[\"']([^\"']+)[\"']"),
]


class WeiboLoginInfo:
    """微博登录态校验结果。"""

    def __init__(self, logged_in: bool, uid: str | None = None, screen_name: str | None = None, message: str = "") -> None:
        self.logged_in = logged_in
        self.uid = uid
        self.screen_name = screen_name
        self.message = message


class BrowserCookieProvider:
    """按“手动 Cookie → 已保存登录态 → 浏览器 Cookie 库”的顺序自动加载微博登录态。"""

    def __init__(self, browser_name: str | None = None) -> None:
        self.browser_name = (browser_name or settings.cookie_browser).lower()

    # ------------------------------------------------------------------
    # 统一入口：自动识别并加载可用登录态
    # ------------------------------------------------------------------
    def load(self) -> tuple[RequestsCookieJar, str]:
        """依优先级尝试所有 Cookie 来源，返回 (cookie_jar, source)。"""

        errors: list[str] = []

        if settings.cookie_string and settings.cookie_string.strip():
            try:
                return self._jar_from_cookie_string(settings.cookie_string), "manual"
            except Exception as exc:
                errors.append(f"手动 Cookie 不可用: {exc}")

        if settings.state_file.exists():
            try:
                return self._jar_from_storage_state(settings.state_file), "saved"
            except Exception as exc:
                errors.append(f"已保存登录态不可用: {exc}")

        try:
            return self._jar_from_browser_database(), "browser"
        except Exception as exc:
            errors.append(f"浏览器 Cookie 读取失败: {exc}")

        raise RuntimeError(
            "未能自动识别微博登录态。" + ("；".join(errors) if errors else "") +
            " 请点击“自动获取 Cookie”登录一次微博，或手动粘贴请求 Cookie。"
        )

    def _read_cookie_jar(self) -> RequestsCookieJar:
        return self.load()[0]

    def load_saved_state(self) -> RequestsCookieJar:
        """仅读取程序自动保存的登录态文件。"""

        if not settings.state_file.exists():
            raise RuntimeError("尚无自动保存的登录态文件。")
        return self._jar_from_storage_state(settings.state_file)

    # ------------------------------------------------------------------
    # 来源 1：手动 Cookie 字符串
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 来源 2：程序自动保存的 Playwright storage state（backend/data/weibo_state.json）
    # ------------------------------------------------------------------
    def _jar_from_storage_state(self, state_path: Path) -> RequestsCookieJar:
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"登录态文件读取失败: {state_path}") from exc

        raw_cookies = payload.get("cookies") if isinstance(payload, dict) else None
        if not isinstance(raw_cookies, list):
            raise RuntimeError("登录态文件格式不正确，缺少 cookies 字段。")

        jar = RequestsCookieJar()
        for item in raw_cookies:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "")
            if "weibo.com" not in domain and "weibo.cn" not in domain:
                continue
            name = str(item.get("name") or "")
            value = item.get("value")
            if not name or value is None:
                continue
            jar.set(
                name,
                str(value),
                domain=domain or ".weibo.com",
                path=str(item.get("path") or "/"),
                secure=bool(item.get("secure")),
            )
        if not jar:
            raise RuntimeError("登录态文件中没有 weibo.com 域的有效 Cookie。")
        return jar

    # ------------------------------------------------------------------
    # 来源 3：本机 Edge/Chrome Cookie 数据库（含被浏览器锁定时的兜底读取）
    # ------------------------------------------------------------------
    def _jar_from_browser_database(self) -> RequestsCookieJar:
        source = self._resolve_cookie_file()
        cookie_file, temp_dir = self._materialize_cookie_file(source)
        try:
            if self.browser_name == "edge":
                return browser_cookie3.edge(cookie_file=str(cookie_file), domain_name="weibo.com")
            if self.browser_name == "chrome":
                return browser_cookie3.chrome(cookie_file=str(cookie_file), domain_name="weibo.com")
            raise RuntimeError(f"暂不支持的浏览器类型: {self.browser_name}")
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _materialize_cookie_file(self, source: Path) -> tuple[Path, Path | None]:
        """把浏览器 Cookie 数据库准备成本地进程可读的文件，浏览器运行锁定时自动兜底。"""

        temp_dir = Path(tempfile.mkdtemp(prefix="weibo-cookie-"))
        cookie_file = temp_dir / "Cookies"
        try:
            shutil.copy2(source, cookie_file)
            return cookie_file, temp_dir
        except (PermissionError, OSError):
            # Edge/Chrome 运行时可能锁定数据库，改用 SQLite immutable 只读模式备份。
            try:
                uri = f"file:{source.as_posix()}?immutable=1"
                with sqlite3.connect(uri, uri=True) as locked_conn:
                    locked_conn.backup(sqlite3.connect(str(cookie_file)))
                return cookie_file, temp_dir
            except Exception as exc:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise RuntimeError(
                    "浏览器 Cookie 数据库已被 Edge/Chrome 或 Windows 锁定，且无法通过只读模式读取。"
                ) from exc

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

    # ------------------------------------------------------------------
    # 登录态校验：请求微博首页，从 HTML 中识别当前登录 uid / 昵称
    # ------------------------------------------------------------------
    def validate_login(self, session: requests.Session | None = None) -> WeiboLoginInfo:
        session = session or self.build_requests_session()
        try:
            response = session.get(
                WEIBO_HOME_URL,
                timeout=settings.request_timeout,
                headers={"Referer": "https://weibo.com/"},
                allow_redirects=True,
            )
        except Exception as exc:
            return WeiboLoginInfo(False, message=f"访问微博失败: {exc}")

        if response.status_code != 200:
            return WeiboLoginInfo(False, message=f"微博返回 HTTP {response.status_code}，登录态可能失效。")

        text = response.text
        uid = None
        for pattern in UID_PATTERNS:
            match = pattern.search(text)
            if match:
                uid = match.group(1)
                break

        if "login.php" in str(response.url) or not uid:
            return WeiboLoginInfo(False, message="微博当前未登录或登录态已过期。")

        screen_name = None
        for pattern in NICK_PATTERNS:
            match = pattern.search(text)
            if match:
                screen_name = match.group(1)
                break

        return WeiboLoginInfo(True, uid=uid, screen_name=screen_name, message="已识别微博登录态。")

    def build_requests_session(self) -> requests.Session:
        try:
            jar, _source = self.load()
        except Exception as exc:
            raise RuntimeError(
                f"读取微博登录态失败：{exc} 可点击“自动获取 Cookie”登录一次微博；"
                "或在登录态设置中保存微博请求 Cookie。"
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
            jar, _source = self.load()
        except Exception as exc:
            raise RuntimeError(
                f"读取微博登录态失败：{exc} 可点击“自动获取 Cookie”登录一次微博。"
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
