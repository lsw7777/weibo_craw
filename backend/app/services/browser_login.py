from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from app.core.config import settings
from app.models.schemas import AuthCookieStatus
from app.services.browser_auth import BrowserCookieProvider
from app.services.playwright_runner import run_playwright_sync


logger = logging.getLogger("weibo.auth")

# 同一时间只允许一个自动获取任务（弹出的浏览器窗口与用户数据目录不能被两个进程共用）。
_capture_lock = threading.Lock()


class BrowserLoginService:
    """自动识别微博登录态；必要时打开浏览器让用户登录一次，并自动捕获 Cookie。"""

    def __init__(self, cookie_provider: BrowserCookieProvider | None = None) -> None:
        self.cookie_provider = cookie_provider or BrowserCookieProvider()

    def capture_login(self) -> AuthCookieStatus:
        if not _capture_lock.acquire(blocking=False):
            raise RuntimeError(
                "已有一个“自动获取 Cookie”任务正在进行：请在弹出的浏览器窗口中完成微博登录，等待其结束后再试。"
            )

        try:
            # 1) 当前已经能自动识别有效登录态时，直接返回，无需重新登录。
            try:
                existing = self._current_status(check_login=True)
            except Exception as exc:
                # 登录态检测自身的异常不应阻断自动获取流程。
                logger.warning("登录态预检测出错（继续尝试弹出浏览器）：%s", exc)
                existing = None
            if existing and existing.readable and existing.cookie_count:
                return existing

            # 2) 打开浏览器让用户登录一次；只有 Requests 校验通过（真实登录）才保存。
            self._capture_via_browser()

            # 3) 重新校验并返回刚保存的新登录态（避免旧的手动 Cookie 干扰）。
            status = self._current_status(check_login=True, prefer_saved=True)
            if not status.readable:
                # 理论上不会走到这里：只有校验通过才会保存；防御性清理坏状态文件。
                self._discard_state_file()
                raise RuntimeError(f"自动获取的 Cookie 未通过登录校验：{status.message}")
            status.message = f"已自动捕获微博登录 Cookie 并保存，后续将自动加载。 {status.message}".strip()
            return status
        finally:
            _capture_lock.release()

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

    def _discard_state_file(self) -> None:
        try:
            settings.state_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _capture_via_browser(self) -> None:
        """弹出浏览器打开微博，轮询等待用户真实登录（Requests 校验），成功后才保存 storage state。

        通过 run_playwright_sync 在工作线程中运行，规避 uvicorn --reload 在
        Windows 上设置 SelectorEventLoopPolicy 导致的 NotImplementedError。
        """

        settings.state_file.parent.mkdir(parents=True, exist_ok=True)
        timeout_seconds = max(settings.auto_login_timeout, 30)
        run_playwright_sync(lambda: self._capture_once(timeout_seconds))

    def _capture_once(self, timeout_seconds: int) -> None:
        temp_profile_dir: Path | None = None
        context: Any | None = None

        from playwright.sync_api import Error as PlaywrightError

        try:
            with sync_playwright() as playwright:
                context, temp_profile_dir = self._launch_context(playwright)
                logger.info("浏览器窗口已启动，正在打开微博页面...")
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    try:
                        page.goto("https://weibo.com/", wait_until="domcontentloaded", timeout=60_000)
                    except PlaywrightError as exc:
                        raise RuntimeError(f"打开微博页面失败：{exc} 请检查本机网络或代理设置后重试。") from exc

                    logger.info("已打开微博页面，等待你在窗口中登录微博（最长 %s 秒）...", timeout_seconds)
                    deadline = time.monotonic() + timeout_seconds
                    verified = False
                    while time.monotonic() < deadline:
                        cookies = context.cookies("https://weibo.com/")
                        has_sub = any(c.get("name") == "SUB" and c.get("value") for c in cookies)
                        if has_sub:
                            # 微博对未登录游客也会发放 SUB Cookie，
                            # 必须用 Requests 请求微博首页校验是否为真实登录。
                            info = self.cookie_provider.validate_playwright_cookies(cookies)
                            if info.logged_in:
                                # 稍等页面写完其余 Cookie 再持久化。
                                page.wait_for_timeout(3_000)
                                context.storage_state(path=str(settings.state_file))
                                verified = True
                                break
                        page.wait_for_timeout(1_500)

                    if not verified:
                        raise RuntimeError(
                            f"等待微博登录超时（{timeout_seconds} 秒）：请在弹出的浏览器窗口中完成登录"
                            "（扫码或账号密码）后再等待自动捕获。"
                        )
                finally:
                    context.close()
        except RuntimeError:
            raise
        except PlaywrightError as exc:
            raise RuntimeError(
                f"自动登录窗口运行失败：{exc} 若提示浏览器未安装，请先执行 python -m playwright install chromium。"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"自动登录窗口启动失败：{exc}") from exc
        finally:
            if temp_profile_dir is not None:
                shutil.rmtree(temp_profile_dir, ignore_errors=True)

    def _launch_context(self, playwright) -> tuple[Any, Path | None]:
        """依次尝试：默认配置目录 chromium → 系统 Edge → 全新临时目录 chromium → 临时目录 Edge。

        返回 (context, 临时目录)。临时目录由调用方负责清理。
        默认配置目录可能被上一次未退出的浏览器进程锁定，用全新临时目录可以兜底。
        """

        from playwright.sync_api import Error as PlaywrightError

        temp_dir = Path(tempfile.mkdtemp(prefix="weibo-login-"))
        candidates: list[tuple[str, Path, dict[str, Any]]] = [
            ("chromium + 默认配置目录", settings.browser_profile_dir, {}),
            ("系统 Edge + 默认配置目录", settings.browser_profile_dir, {"channel": "msedge"}),
            ("chromium + 全新临时目录", temp_dir, {}),
            ("系统 Edge + 全新临时目录", temp_dir, {"channel": "msedge"}),
        ]

        errors: list[str] = []
        for label, user_data_dir, extra in candidates:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=False,
                    viewport={"width": 1280, "height": 860},
                    **extra,
                )
                logger.info("已启动浏览器：%s", label)
                if label.endswith("全新临时目录"):
                    return context, temp_dir
                return context, None
            except PlaywrightError as exc:
                detail = " ".join(str(exc).split())[:200]
                errors.append(f"{label}: {detail}")
                logger.warning("浏览器启动失败（%s）：%s", label, detail)

        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(
            "无法启动浏览器窗口（已尝试 chromium / 系统 Edge / 全新临时配置目录）。"
            "请先执行 python -m playwright install chromium 后重试。详细错误："
            + " | ".join(errors)
        )
