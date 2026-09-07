from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def run_playwright_sync(func: Callable[[], T]) -> T:
    """在独立工作线程中运行 Playwright 同步 API，并修复 Windows 事件循环策略。

    背景：uvicorn 在 Windows 上（尤其 --reload 模式）会把全局事件循环策略改为
    SelectorEventLoopPolicy，而 SelectorEventLoop 不支持 asyncio 子进程，
    导致 sync_playwright() 启动 node 驱动进程时抛出 NotImplementedError。

    解决：在工作线程内临时把策略切回 Windows 默认的 ProactorEventLoopPolicy，
    让 Playwright 正常创建驱动进程，结束后恢复原策略，不影响 uvicorn 自身。
    """

    if sys.platform != "win32":
        return func()

    outcome: dict[str, Any] = {}

    def worker() -> None:
        previous_policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        try:
            outcome["value"] = func()
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc
        finally:
            asyncio.set_event_loop_policy(previous_policy)

    thread = threading.Thread(target=worker, name="weibo-playwright", daemon=True)
    thread.start()
    thread.join()

    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")  # type: ignore[return-value]
