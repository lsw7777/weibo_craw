from __future__ import annotations

from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.models.schemas import (
    AccountResolveRequest,
    AccountSearchResult,
    AuthCookieStatus,
    AuthCookieUpdateRequest,
    FollowOperationRequest,
    FollowOperationResponse,
    FollowingListResponse,
    ResolvedAccountResult,
    ScrapeAccountsConfig,
    ScrapeRequest,
    ScrapeResponse,
)
from app.services.auth_config import AuthConfigService
from app.services.follow_service import WeiboFollowService
from app.services.scrape_config import ScrapeConfigService
from app.services.weibo_client import WeiboCrawlerService


app = FastAPI(title=settings.project_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/downloads", StaticFiles(directory=str(settings.download_dir)), name="downloads")


@app.get(f"{settings.api_prefix}/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(f"{settings.api_prefix}/media/proxy")
def proxy_media(url: str = Query(..., min_length=1)) -> Response:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="只允许代理 http/https 图片地址。")

    host = parsed.hostname or ""
    allowed_suffixes = ("sinaimg.cn", "sina.com.cn", "weibo.com", "weibo.cn")
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in allowed_suffixes):
        raise HTTPException(status_code=400, detail="不允许代理该图片域名。")

    try:
        upstream = requests.get(
            url,
            timeout=settings.request_timeout,
            headers={
                "User-Agent": settings.api_user_agent,
                "Referer": "https://weibo.com/",
            },
        )
        upstream.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"图片代理失败: {exc}") from exc

    media_type = upstream.headers.get("content-type") or "image/jpeg"
    return Response(
        content=upstream.content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get(f"{settings.api_prefix}/auth/cookie/status", response_model=AuthCookieStatus)
def get_cookie_status() -> AuthCookieStatus:
    service = AuthConfigService()
    return service.get_status()


@app.post(f"{settings.api_prefix}/auth/cookie", response_model=AuthCookieStatus)
def save_cookie(payload: AuthCookieUpdateRequest) -> AuthCookieStatus:
    try:
        service = AuthConfigService()
        return service.save_cookie_string(payload.cookie_string)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/accounts/resolve", response_model=list[ResolvedAccountResult])
def resolve_accounts(payload: AccountResolveRequest) -> list[ResolvedAccountResult]:
    try:
        service = WeiboCrawlerService()
        return service.resolve_accounts(payload.accounts)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/config/scrape-accounts", response_model=ScrapeAccountsConfig)
def get_scrape_accounts_config() -> ScrapeAccountsConfig:
    try:
        service = ScrapeConfigService()
        return service.load_accounts()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/config/scrape-accounts", response_model=ScrapeAccountsConfig)
def save_scrape_accounts_config(payload: ScrapeAccountsConfig) -> ScrapeAccountsConfig:
    try:
        service = ScrapeConfigService()
        return service.save_accounts(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/scrape", response_model=ScrapeResponse)
def scrape_accounts(payload: ScrapeRequest) -> ScrapeResponse:
    try:
        service = WeiboCrawlerService()
        return service.scrape_accounts(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/accounts/search", response_model=list[AccountSearchResult])
def search_accounts(
    q: str = Query(..., min_length=1, description="微博账号关键词"),
    limit: int = Query(default=10, ge=1, le=20),
) -> list[AccountSearchResult]:
    try:
        service = WeiboFollowService()
        return service.search_accounts(q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/accounts/following", response_model=FollowingListResponse)
def list_following(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> FollowingListResponse:
    try:
        service = WeiboFollowService()
        return service.list_following(page=page, page_size=page_size)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/accounts/follow", response_model=FollowOperationResponse)
def follow_accounts(payload: FollowOperationRequest) -> FollowOperationResponse:
    try:
        service = WeiboFollowService()
        return service.apply_operation(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
