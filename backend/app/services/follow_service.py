from __future__ import annotations

import re
from html import unescape
from contextlib import contextmanager

from playwright.sync_api import Page, sync_playwright
from requests import Session

from app.core.config import settings
from app.models.schemas import (
    AccountSearchResult,
    FollowOperationItem,
    FollowOperationRequest,
    FollowOperationResponse,
    FollowingListResponse,
)
from app.services.browser_auth import BrowserCookieProvider
from app.utils.text import extract_uid, normalize_profile_url, normalize_space, strip_html


FOLLOW_PATTERN = re.compile(r"关注|已关注|互相关注")


class WeiboFollowService:
    def __init__(self) -> None:
        self.cookie_provider = BrowserCookieProvider()
        self.session: Session = self.cookie_provider.build_requests_session()

    def search_accounts(self, query: str, limit: int = 10) -> list[AccountSearchResult]:
        normalized_query = normalize_space(query)
        if not normalized_query:
            return []

        response = self.session.get(
            "https://s.weibo.com/user",
            params={"q": normalized_query},
            timeout=settings.request_timeout,
            headers={"Referer": "https://s.weibo.com/"},
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        return self._parse_search_html(response.text, limit=limit)

    def list_following(self, page: int = 1, page_size: int = 20) -> FollowingListResponse:
        uid, screen_name = self._get_current_user()
        payload = self._get_json(
            "https://weibo.com/ajax/friendships/friends",
            params={"uid": uid, "page": page, "count": page_size},
        )
        users = payload.get("users", [])
        items = [self._parse_user_item(user) for user in users[:page_size] if isinstance(user, dict)]
        total_number = int(payload.get("total_number") or len(items))
        next_cursor = int(payload.get("next_cursor") or 0)

        return FollowingListResponse(
            uid=uid,
            screen_name=payload.get("screenName") or screen_name,
            page=page,
            page_size=page_size,
            total_number=total_number,
            has_next=bool(next_cursor) or page * page_size < total_number,
            items=items,
        )

    def apply_operation(self, payload: FollowOperationRequest) -> FollowOperationResponse:
        items: list[FollowOperationItem] = []
        success_count = 0
        failure_count = 0

        for target in payload.targets:
            try:
                detail = self._apply_single_http_action(target=target, action=payload.action)
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

    def _apply_single_http_action(self, target: str, action: str) -> str:
        uid = extract_uid(target)
        if not uid:
            raise RuntimeError(f"无法识别账号 UID: {target}")

        profile_url = f"https://weibo.com/u/{uid}"
        headers = {
            "Referer": profile_url,
            "Origin": "https://weibo.com",
            "X-Requested-With": "XMLHttpRequest",
        }
        xsrf_token = self.session.cookies.get("XSRF-TOKEN")
        if xsrf_token:
            headers["X-XSRF-TOKEN"] = xsrf_token

        if action == "follow":
            response = self.session.post(
                "https://weibo.com/aj/f/followed",
                params={"ajwvr": 6},
                data={
                    "uid": uid,
                    "objectid": "",
                    "f": "1",
                    "extra": "",
                    "refer_sort": "",
                    "refer_flag": "1005050001_",
                    "location": "page_100505_home",
                    "oid": uid,
                    "wforce": "1",
                    "nogroup": "false",
                    "_t": "0",
                },
                headers=headers,
                timeout=settings.request_timeout,
            )
            return self._parse_operation_response(response=response, success_text="关注成功")

        response = self.session.post(
            "https://weibo.com/aj/f/unfollow",
            params={"ajwvr": 6},
            data={
                "uid": uid,
                "f": "1",
                "refer_flag": "1005050001_",
                "location": "page_100505_home",
                "_t": "0",
            },
            headers=headers,
            timeout=settings.request_timeout,
        )
        return self._parse_operation_response(response=response, success_text="取关成功")

    def _parse_operation_response(self, response, success_text: str) -> str:
        if response.status_code == 403:
            raise RuntimeError("微博接口返回 403，请重新配置登录 Cookie。")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"微博关注接口返回非 JSON 数据: {response.text[:120]}") from exc

        code = str(payload.get("code", ""))
        message = normalize_space(payload.get("msg")) or success_text
        if code == "100000":
            return message if message != "" else success_text
        raise RuntimeError(message or f"微博接口返回错误码 {code}")

    @contextmanager
    def _page_session(self):
        try:
            cookies = self.cookie_provider.build_playwright_cookies()
        except Exception as exc:
            raise RuntimeError("无法读取微博登录态，请先在 Edge/Chrome 中登录微博。") from exc

        try:
            with sync_playwright() as playwright:
                browser = self._launch_browser(playwright)
                context = browser.new_context()
                context.add_cookies(cookies)
                page = context.new_page()
                yield page
                context.close()
                browser.close()
        except Exception as exc:
            raise RuntimeError(
                f"Playwright 启动或页面操作失败：{exc}"
            ) from exc

    def _launch_browser(self, playwright):
        try:
            return playwright.chromium.launch(headless=settings.playwright_headless)
        except Exception as first_exc:
            try:
                return playwright.chromium.launch(channel="msedge", headless=settings.playwright_headless)
            except Exception as second_exc:
                raise RuntimeError(
                    "无法启动 Playwright Chromium，也无法回退到本机 Edge。"
                    f"Chromium 错误：{first_exc}; Edge 错误：{second_exc}"
                ) from second_exc

    def _get_json(self, url: str, params: dict) -> dict:
        response = self.session.get(url, params=params, timeout=settings.request_timeout)
        if response.status_code == 403:
            raise RuntimeError("微博接口返回 403，请重新配置登录 Cookie。")
        response.raise_for_status()
        return response.json()

    def _get_current_user(self) -> tuple[str, str]:
        response = self.session.get("https://weibo.com/", timeout=settings.request_timeout)
        response.raise_for_status()
        response.encoding = "utf-8"
        text = response.text
        patterns = [
            r":user=\"\{\s*id:\s*'(\d+)'.*?name:\s*'([^']*)'",
            r'"uid"\s*:\s*"?(\d+)"?',
            r"\$CONFIG\[['\"]uid['\"]\]\s*=\s*['\"]?(\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.S)
            if not match:
                continue
            uid = match.group(1)
            name = unescape(match.group(2)) if len(match.groups()) > 1 else f"用户{uid}"
            return uid, normalize_space(name)
        raise RuntimeError("无法识别当前登录账号 UID，请确认微博登录态仍有效。")

    def _parse_search_html(self, html_text: str, limit: int) -> list[AccountSearchResult]:
        results: list[AccountSearchResult] = []
        seen: set[str] = set()
        card_pattern = re.compile(
            r'<div class="card card-user-b.*?(?=<div class="card card-user-b|\Z)',
            flags=re.S,
        )

        for card_match in card_pattern.finditer(html_text):
            card = card_match.group(0)
            uid_match = re.search(r'href=["\'](?:https?:)?//weibo\.com/u/(\d+)', card)
            if not uid_match:
                continue
            uid = uid_match.group(1)
            if uid in seen:
                continue

            name_match = re.search(r'<a[^>]*class=["\']name["\'][^>]*>(.*?)</a>', card, flags=re.S)
            name = strip_html(name_match.group(1)) if name_match else ""
            if not name:
                continue

            avatar_match = re.search(r'<img[^>]+src=["\']([^"\']+)', card)
            intro_match = re.search(r"<p[^>]*>(.*?)</p>", card, flags=re.S)
            intro = strip_html(intro_match.group(1)) if intro_match else None

            seen.add(uid)
            results.append(
                AccountSearchResult(
                    uid=uid,
                    screen_name=name,
                    profile_url=f"https://weibo.com/u/{uid}",
                    intro=intro,
                    avatar_url=unescape(avatar_match.group(1)) if avatar_match else None,
                    following="已关注" in card or "取消关注" in card,
                )
            )
            if len(results) >= limit:
                break

        return results

    def _parse_user_item(self, user: dict) -> AccountSearchResult:
        uid = str(user.get("idstr") or user.get("id") or "")
        return AccountSearchResult(
            uid=uid,
            screen_name=user.get("screen_name") or user.get("name") or uid,
            profile_url=f"https://weibo.com/u/{uid}",
            intro=normalize_space(user.get("description")),
            avatar_url=user.get("profile_image_url") or user.get("avatar_large") or user.get("avatar_hd"),
            followers_count=user.get("followers_count"),
            friends_count=user.get("friends_count"),
            statuses_count=user.get("statuses_count"),
            following=user.get("following"),
        )

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
