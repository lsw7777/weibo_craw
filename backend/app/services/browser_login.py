from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from app.core.config import settings
from app.models.schemas import AuthCookieStatus
from app.services.browser_auth import BrowserCookieProvider


class BrowserLoginService:
    """自动识别微博登录态；必要时打开浏览器让用户登录一次，并自动捕获 Cookie。"""

    def __init__(self, cookie_provider: BrowserCookieProvider | None = None) -> None:
        self.cookie_provider = cookie_provider or BrowserCookieProvider()

    def capture_login(self) -> AuthCookieStatus:
        # 1) 当前已经能自动识别登录态时，直接返回，无需重新登录。
        existing = self._current_status(check_login=True)
        if existing.readable and existing.cookie_count:
            return existing

        # 2) 打开浏览器让用户登录一次，自动捕获 Cookie 并持久化。
        message = self._capture_via_browser()

        # 3) 捕获成功后优先校验并返回刚保存的新登录态（避免旧的手动 Cookie 干扰）。
        status = self._current_status(check_login=True, prefer_saved=True)
        status.message = f"{message} {status.message}".strip()
        return status

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _current_status(self, check_login: bool = False, prefer_saved: bool = False) -> AuthCookieStatus:
        auth_service_cookie_string = (settings.cookie_string or "").strip()
        try:
            if prefer_saved:
                jar = self.cookie_provider.load_saved_state()
                source = "saved"
            else:
                jar, source = self.cookie_provider.load()
        except Exception as exc:
            return AuthCookieStatus(
                configured=bool(auth_service_cookie_string),
                readable=False,
                source="none",
                cookie_count=0,
                message=str(exc),
                cookie_string=auth_service_cookie_string,
            )

        uid = None
        screen_name = None
        message = "已自动加载微博登录态。"
        if check_login:
            info = self.cookie_provider.validate_login()
            if not info.logged_in:
                return AuthCookieStatus(
                    configured=bool(auth_service_cookie_string),
                    readable=False,
                    source="none",
                    cookie_count=0,
                    message=f"Cookie 已加载，但登录态校验失败：{info.message}",
                    cookie_string=auth_service_cookie_string,
                )
            uid = info.uid
            screen_name = info.screen_name
            message = info.message
            if screen_name:
                message = f"{message} 当前账号：{screen_name}。"

        return AuthCookieStatus(
            configured=bool(auth_service_cookie_string),
            readable=True,
            source=source,  # type: ignore[arg-type]
            cookie_count=len(list(jar)),
            message=message,
            cookie_string=auth_service_cookie_string,
            uid=uid,
            screen_name=screen_name,
        )

    def _capture_via_browser(self) -> str:
        settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        settings.state_file.parent.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import Error as PlaywrightError

        try:
            with sync_playwright() as playwright:
                try:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(settings.browser_profile_dir),
                        headless=False,
                        viewport={"width": 1280, "height": 860},
                    )
                except PlaywrightError:
                    # 本机未安装 chromium 时回退到系统 Edge。
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(settings.browser_profile_dir),
                        channel="msedge",
                        headless=False,
                        viewport={"width": 1280, "height": 860},
                    )

                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.goto("https://weibo.com/", wait_until="domcontentloaded", timeout=60_000)

                    deadline = time.monotonic() + max(settings.auto_login_timeout, 30)
                    while time.monotonic() < deadline:
                        cookies = context.cookies("https://weibo.com/")
                        if any(cookie.get("name") == "SUB" and cookie.get("value") for cookie in cookies):
                            # SUB 出现后再等待页面写入其余 Cookie。
                            page.wait_for_timeout(3_000)
                            break
                        page.wait_for_timeout(1_000)
                    else:
                        raise RuntimeError(
                            f"等待登录超时（{settings.auto_login_timeout} 秒），请在弹出窗口中完成微博登录后重试。"
                        )

                    context.storage_state(path=str(settings.state_file))
                finally:
                    context.close()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"自动登录窗口启动失败：{exc} 请确认已执行 python -m playwright install chromium。") from exc

        return "已捕获微博登录 Cookie 并保存到本地，后续将自动加载。"
