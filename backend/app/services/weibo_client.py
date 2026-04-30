from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from requests import Session

from app.core.config import PROJECT_ROOT, settings
from app.models.schemas import (
    AccountAnalysis,
    CommentData,
    MediaAsset,
    PostData,
    ScrapeRequest,
    ScrapeResponse,
    ScrapedAccountResult,
)
from app.services.analyzer import ContentAnalyzer
from app.services.browser_auth import BrowserCookieProvider
from app.utils.text import (
    build_public_download_url,
    extract_uid,
    infer_file_extension,
    normalize_space,
    parse_weibo_datetime,
    safe_filename,
    strip_html,
)


class WeiboCrawlerService:
    def __init__(self) -> None:
        self.cookie_provider = BrowserCookieProvider()
        self.session: Session = self.cookie_provider.build_requests_session()
        self.analyzer = ContentAnalyzer()

    def scrape_accounts(self, payload: ScrapeRequest) -> ScrapeResponse:
        results: list[ScrapedAccountResult] = []
        total_posts = 0

        for account in payload.accounts:
            uid = extract_uid(account)
            if not uid:
                raise RuntimeError(f"无法从输入中识别微博 UID: {account}")

            profile = self.fetch_profile(uid)
            posts = self.fetch_posts(
                uid=uid,
                max_posts=payload.max_posts,
                start_time=payload.start_time,
                end_time=payload.end_time,
                fetch_comments=payload.fetch_comments,
                max_comments_per_post=payload.max_comments_per_post,
                download_images=payload.download_images,
            )
            total_posts += len(posts)

            analysis = self.build_analysis(posts)
            export_file = None
            result = ScrapedAccountResult(
                requested_account=account,
                uid=uid,
                screen_name=profile.get("screen_name") or uid,
                profile_url=f"https://weibo.com/u/{uid}",
                description=profile.get("description"),
                followers_count=profile.get("followers_count"),
                friends_count=profile.get("friends_count"),
                statuses_count=profile.get("statuses_count"),
                posts=posts,
                analysis=analysis,
            )

            if payload.save_json:
                export_file = self.save_export(result)
                result.export_file = export_file

            results.append(result)

        return ScrapeResponse(
            generated_at=datetime.now(),
            total_accounts=len(results),
            total_posts=total_posts,
            results=results,
        )

    def fetch_profile(self, uid: str) -> dict[str, Any]:
        payload = self._get_json(
            "https://weibo.com/ajax/profile/info",
            params={"uid": uid},
        )
        data = payload.get("data", payload)
        user = data.get("user", data)
        return {
            "screen_name": user.get("screen_name") or user.get("name"),
            "description": normalize_space(user.get("description")),
            "followers_count": user.get("followers_count"),
            "friends_count": user.get("friends_count"),
            "statuses_count": user.get("statuses_count"),
        }

    def fetch_posts(
        self,
        uid: str,
        max_posts: int | None,
        start_time: datetime | None,
        end_time: datetime | None,
        fetch_comments: bool,
        max_comments_per_post: int,
        download_images: bool,
    ) -> list[PostData]:
        collected: list[PostData] = []

        for page in range(1, settings.max_page_count + 1):
            payload = self._get_json(
                "https://weibo.com/ajax/statuses/mymblog",
                params={"uid": uid, "page": page, "feature": 0},
            )
            data = payload.get("data", payload)
            raw_posts = data.get("list", data if isinstance(data, list) else [])
            if not raw_posts:
                break

            stop_because_old = False
            for raw_post in raw_posts:
                post = self._parse_post(uid=uid, raw_post=raw_post, download_images=download_images)
                if end_time and post.created_at and post.created_at > end_time:
                    continue
                if start_time and post.created_at and post.created_at < start_time:
                    stop_because_old = True
                    continue

                if fetch_comments and max_comments_per_post > 0:
                    post.comments = self.fetch_comments(
                        uid=uid,
                        post_id=post.id,
                        max_comments=max_comments_per_post,
                        download_images=download_images,
                    )

                collected.append(post)
                if max_posts and len(collected) >= max_posts:
                    break

            if stop_because_old or (max_posts and len(collected) >= max_posts):
                break

            time.sleep(settings.request_interval_seconds)

        return collected

    def fetch_comments(
        self,
        uid: str,
        post_id: str,
        max_comments: int,
        download_images: bool,
    ) -> list[CommentData]:
        comments: list[CommentData] = []
        max_id = 0

        while len(comments) < max_comments:
            params = {
                "id": post_id,
                "uid": uid,
                "count": min(20, max_comments - len(comments)),
                "max_id": max_id,
                "is_reload": 1,
                "is_show_bulletin": 2,
                "is_mix": 0,
                "flow": 0,
            }
            payload = self._get_json("https://weibo.com/ajax/statuses/buildComments", params=params)
            data = payload.get("data", payload)
            raw_comments = data if isinstance(data, list) else data.get("data", [])
            if not raw_comments:
                break

            for raw_comment in raw_comments:
                comment = self._parse_comment(
                    uid=uid,
                    post_id=post_id,
                    raw_comment=raw_comment,
                    download_images=download_images,
                )
                comments.append(comment)
                if len(comments) >= max_comments:
                    break

            next_max_id = payload.get("max_id")
            if next_max_id is None and isinstance(data, dict):
                next_max_id = data.get("max_id")
            if not next_max_id:
                break

            max_id = next_max_id
            time.sleep(settings.request_interval_seconds)

        return comments

    def build_analysis(self, posts: list[PostData]) -> AccountAnalysis:
        post_texts = [post.text for post in posts if post.text]
        comment_texts = [comment.text for post in posts for comment in post.comments if comment.text]
        return AccountAnalysis(
            posts=self.analyzer.analyze(post_texts, "博文内容"),
            comments=self.analyzer.analyze(comment_texts, "评论内容"),
        )

    def save_export(self, result: ScrapedAccountResult) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_filename(result.screen_name)}_{result.uid}_{timestamp}.json"
        file_path = settings.export_dir / filename
        file_path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(file_path.relative_to(PROJECT_ROOT))

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=settings.request_timeout)
        if response.status_code == 403:
            raise RuntimeError("微博接口返回 403，请确认 Edge/Chrome 浏览器仍保持微博登录状态。")
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"微博接口返回了非 JSON 数据: {url}") from exc

    def _parse_post(self, uid: str, raw_post: dict[str, Any], download_images: bool) -> PostData:
        post_id = str(raw_post.get("id") or raw_post.get("mid") or raw_post.get("mblogid") or "")
        created_at = parse_weibo_datetime(raw_post.get("created_at"))
        text = normalize_space(raw_post.get("text_raw")) or strip_html(raw_post.get("text"))
        images = self._build_media_assets(
            urls=self._extract_image_urls(raw_post),
            media_dir=Path(uid) / "posts" / safe_filename(post_id),
            download_images=download_images,
        )

        return PostData(
            id=post_id,
            mblogid=raw_post.get("mblogid"),
            created_at=created_at,
            source=strip_html(raw_post.get("source")),
            text=text,
            reposts_count=int(raw_post.get("reposts_count") or 0),
            comments_count=int(raw_post.get("comments_count") or 0),
            attitudes_count=int(raw_post.get("attitudes_count") or 0),
            images=images,
        )

    def _parse_comment(
        self,
        uid: str,
        post_id: str,
        raw_comment: dict[str, Any],
        download_images: bool,
    ) -> CommentData:
        comment_id = str(raw_comment.get("id") or raw_comment.get("mid") or "")
        author = raw_comment.get("user", {}).get("screen_name")
        created_at = parse_weibo_datetime(raw_comment.get("created_at"))
        text = normalize_space(raw_comment.get("text_raw")) or strip_html(raw_comment.get("text"))
        images = self._build_media_assets(
            urls=self._extract_image_urls(raw_comment),
            media_dir=Path(uid) / "comments" / safe_filename(post_id) / safe_filename(comment_id),
            download_images=download_images,
        )

        return CommentData(
            id=comment_id,
            author=author,
            created_at=created_at,
            text=text,
            like_count=int(raw_comment.get("like_counts") or raw_comment.get("like_count") or 0),
            images=images,
        )

    def _extract_image_urls(self, payload: dict[str, Any]) -> list[str]:
        urls: list[str] = []

        pic_infos = payload.get("pic_infos")
        if isinstance(pic_infos, dict):
            for value in pic_infos.values():
                if not isinstance(value, dict):
                    continue
                for key in ("largest", "mw2000", "original", "bmiddle"):
                    candidate = value.get(key)
                    if isinstance(candidate, dict) and candidate.get("url"):
                        urls.append(candidate["url"])
                        break
                    if isinstance(candidate, str):
                        urls.append(candidate)
                        break

        pics = payload.get("pics")
        if isinstance(pics, list):
            for item in pics:
                if not isinstance(item, dict):
                    continue
                large = item.get("large")
                if isinstance(large, dict) and large.get("url"):
                    urls.append(large["url"])
                    continue
                if item.get("url"):
                    urls.append(item["url"])

        page_pic = payload.get("page_info", {}).get("page_pic", {})
        if isinstance(page_pic, dict) and page_pic.get("url"):
            urls.append(page_pic["url"])

        comment_pic = payload.get("pic")
        if isinstance(comment_pic, dict):
            for key in ("large", "url"):
                candidate = comment_pic.get(key)
                if isinstance(candidate, dict) and candidate.get("url"):
                    urls.append(candidate["url"])
                    break
                if isinstance(candidate, str):
                    urls.append(candidate)
                    break

        deduped = []
        seen = set()
        for url in urls:
            if not url or url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped

    def _build_media_assets(self, urls: list[str], media_dir: Path, download_images: bool) -> list[MediaAsset]:
        assets: list[MediaAsset] = []
        for index, url in enumerate(urls, start=1):
            local_path = None
            served_url = None
            if download_images:
                local_path, served_url = self._download_media(url=url, media_dir=media_dir, index=index)
            assets.append(MediaAsset(url=url, local_path=local_path, served_url=served_url))
        return assets

    def _download_media(self, url: str, media_dir: Path, index: int) -> tuple[str | None, str | None]:
        target_dir = settings.download_dir / media_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        extension = infer_file_extension(url)
        filename = f"{index:02d}{extension}"
        file_path = target_dir / filename

        if not file_path.exists():
            response = self.session.get(url, timeout=settings.request_timeout)
            response.raise_for_status()
            file_path.write_bytes(response.content)

        relative_path = file_path.relative_to(settings.download_dir)
        return str(file_path.relative_to(PROJECT_ROOT)), build_public_download_url(relative_path)
