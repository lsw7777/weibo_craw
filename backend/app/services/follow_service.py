from __future__ import annotations

import re
from contextlib import contextmanager
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright

from app.core.config import settings
from app.models.schemas import (
    AccountSearchResult,
    FollowOperationItem,
    FollowOperationRequest,
    FollowOperationResponse,
)
from app.services.browser_auth import BrowserCookieProvider
from app.utils.text import extract_uid, normalize_profile_url, normalize_space


FOLLOW_PATTERN = re.compile(r"关注|已关注|互相关注")


class WeiboFollowService:
    def __init__(self) -> None:
        self.cookie_provider = BrowserCookieProvider()

    def search_accounts(self, query: str, limit: int = 10) -> list[AccountSearchResult]:
        normalized_query = normalize_space(query)
        if not normalized_query:
            return []

        with self._page_session() as page:
            search_url = f"https://s.weibo.com/user?q={quote(normalized_query)}"
            page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)
            return self._parse_search_results(page, limit=limit)

    def apply_operation(self, payload: FollowOperationRequest) -> FollowOperationResponse:
        items: list[FollowOperationItem] = []
        success_count = 0
        failure_count = 0

        with self._page_session() as page:
            for target in payload.targets:
                try:
                    detail = self._apply_single_action(page=page, target=target, action=payload.action)
                    items.append(FollowOperationItem(target=target, status="success", detail=detail))
                    success_count += 1
                except Exception as exc:
                    items.append(FollowOperationItem(target=target, status="failed", detail=str(exc)))
                    failure_count += 1

        return FollowOperationResponse(
            action=payload.action,
            success_count=success_count,
            failure_count=failure_count,
            items=items,
        )

    @contextmanager
    def _page_session(self):
        try:
            cookies = self.cookie_provider.build_playwright_cookies()
        except Exception as exc:
            raise RuntimeError("无法读取微博登录态，请先在 Edge/Chrome 中登录微博。") from exc

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=settings.playwright_headless)
                context = browser.new_context()
                context.add_cookies(cookies)
                page = context.new_page()
                yield page
                context.close()
                browser.close()
        except Exception as exc:
            raise RuntimeError(
                "Playwright 启动失败，请确认已安装浏览器运行时：python -m playwright install chromium"
            ) from exc

    def _parse_search_results(self, page: Page, limit: int) -> list[AccountSearchResult]:
        results: list[AccountSearchResult] = []
        seen: set[str] = set()
        anchors = page.locator("a[href*='/u/']")
        candidate_count = min(anchors.count(), limit * 8 + 10)

        for index in range(candidate_count):
            anchor = anchors.nth(index)
            try:
                href = anchor.get_attribute("href") or ""
                uid = extract_uid(href)
                name = normalize_space(anchor.inner_text())
            except Exception:
                continue
            if not uid or not name or uid in seen:
                continue

            profile_url = href
            if profile_url.startswith("//"):
                profile_url = f"https:{profile_url}"
            elif profile_url.startswith("/"):
                profile_url = f"https://weibo.com{profile_url}"

            intro = None
            try:
                card = anchor.locator("xpath=ancestor::div[contains(@class, 'card') or contains(@class, 'card-wrap')][1]")
                intro_locator = card.locator("p")
                if intro_locator.count() > 0:
                    intro = normalize_space(intro_locator.nth(0).inner_text())
            except Exception:
                intro = None

            seen.add(uid)
            results.append(
                AccountSearchResult(
                    uid=uid,
                    screen_name=name,
                    profile_url=profile_url,
                    intro=intro,
                )
            )
            if len(results) >= limit:
                break

        return results

    def _apply_single_action(self, page: Page, target: str, action: str) -> str:
        profile_url = normalize_profile_url(target)
        page.goto(profile_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)

        button, button_text = self._find_follow_button(page)
        if not button:
            raise RuntimeError("未找到关注按钮，可能页面结构变化或账号不可访问。")

        state = "followed" if ("已关注" in button_text or "互相关注" in button_text) else "not_following"
        if action == "follow":
            if state == "followed":
                return "账号已经处于关注状态"
            button.click(timeout=5_000)
            page.wait_for_timeout(1_200)
            return "关注成功"

        if state == "not_following":
            return "账号当前未关注"

        button.hover(timeout=5_000)
        page.wait_for_timeout(400)
        menu_item = self._find_clickable_by_text(page, re.compile(r"取消关注"))
        if menu_item:
            menu_item.click(timeout=5_000)
        else:
            button.click(timeout=5_000)

        page.wait_for_timeout(500)
        confirm_button = self._find_clickable_by_text(page, re.compile(r"确定|确认"))
        if confirm_button:
            confirm_button.click(timeout=5_000)
            page.wait_for_timeout(1_000)
        return "取关成功"

    def _find_follow_button(self, page: Page):
        candidates = page.locator("button, a, [role='button']")
        for index in range(min(candidates.count(), 100)):
            locator = candidates.nth(index)
            try:
                text = normalize_space(locator.inner_text(timeout=1_000))
            except Exception:
                continue
            if FOLLOW_PATTERN.search(text):
                return locator, text
        return None, ""

    def _find_clickable_by_text(self, page: Page, pattern: re.Pattern[str]):
        candidates = page.locator("button, a, [role='button'], span")
        for index in range(min(candidates.count(), 120)):
            locator = candidates.nth(index)
            try:
                text = normalize_space(locator.inner_text(timeout=500))
            except Exception:
                continue
            if pattern.search(text):
                return locator
        return None
