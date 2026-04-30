from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.models.schemas import (
    AccountSearchResult,
    AuthCookieStatus,
    AuthCookieUpdateRequest,
    FollowOperationRequest,
    FollowOperationResponse,
    ScrapeRequest,
    ScrapeResponse,
)
from app.services.auth_config import AuthConfigService
from app.services.follow_service import WeiboFollowService
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


@app.post(f"{settings.api_prefix}/accounts/follow", response_model=FollowOperationResponse)
def follow_accounts(payload: FollowOperationRequest) -> FollowOperationResponse:
    try:
        service = WeiboFollowService()
        return service.apply_operation(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
