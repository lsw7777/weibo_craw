from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MediaAsset(BaseModel):
    url: str
    local_path: str | None = None
    served_url: str | None = None


class CommentData(BaseModel):
    id: str
    author: str | None = None
    created_at: datetime | None = None
    text: str
    like_count: int | None = None
    images: list[MediaAsset] = Field(default_factory=list)


class PostData(BaseModel):
    id: str
    mblogid: str | None = None
    created_at: datetime | None = None
    source: str | None = None
    text: str
    reposts_count: int = 0
    comments_count: int = 0
    attitudes_count: int = 0
    images: list[MediaAsset] = Field(default_factory=list)
    comments: list[CommentData] = Field(default_factory=list)


class AnalysisSection(BaseModel):
    summary: str
    topics: list[str] = Field(default_factory=list)
    viewpoints: list[str] = Field(default_factory=list)
    sentiment: Literal["正面", "负面", "中性", "分化"]
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0


class AccountAnalysis(BaseModel):
    posts: AnalysisSection
    comments: AnalysisSection


class ScrapedAccountResult(BaseModel):
    requested_account: str
    uid: str
    screen_name: str
    profile_url: str
    description: str | None = None
    followers_count: int | None = None
    friends_count: int | None = None
    statuses_count: int | None = None
    posts: list[PostData] = Field(default_factory=list)
    analysis: AccountAnalysis
    export_file: str | None = None


class ScrapeRequest(BaseModel):
    accounts: list[str] = Field(min_length=1)
    max_posts: int | None = Field(default=20, ge=1, le=200)
    start_time: datetime | None = None
    end_time: datetime | None = None
    fetch_comments: bool = True
    max_comments_per_post: int = Field(default=20, ge=0, le=100)
    download_images: bool = True
    save_json: bool = True


class ScrapeResponse(BaseModel):
    generated_at: datetime
    total_accounts: int
    total_posts: int
    results: list[ScrapedAccountResult]


class AccountSearchResult(BaseModel):
    uid: str
    screen_name: str
    profile_url: str
    intro: str | None = None


class FollowOperationRequest(BaseModel):
    action: Literal["follow", "unfollow"]
    targets: list[str] = Field(min_length=1)


class FollowOperationItem(BaseModel):
    target: str
    status: str
    detail: str


class FollowOperationResponse(BaseModel):
    action: Literal["follow", "unfollow"]
    success_count: int
    failure_count: int
    items: list[FollowOperationItem]


class AuthCookieStatus(BaseModel):
    configured: bool
    readable: bool
    source: Literal["manual", "browser", "none"]
    cookie_count: int = 0
    message: str


class AuthCookieUpdateRequest(BaseModel):
    cookie_string: str = Field(min_length=8)
