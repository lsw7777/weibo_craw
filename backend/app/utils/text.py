from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from dateutil import parser as date_parser


WEIBO_TIME_FORMAT = "%a %b %d %H:%M:%S %z %Y"


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def strip_html(raw_html: str | None) -> str:
    if not raw_html:
        return ""
    without_breaks = raw_html.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    no_tags = re.sub(r"<[^>]+>", "", without_breaks)
    return normalize_space(html.unescape(no_tags))


def parse_weibo_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    try:
        parsed = date_parser.parse(raw)
        if parsed.tzinfo:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError, OverflowError):
        for fmt in (WEIBO_TIME_FORMAT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, fmt)
                if parsed.tzinfo:
                    return parsed.astimezone().replace(tzinfo=None)
                return parsed
            except ValueError:
                continue
    return None


def extract_uid(account: str) -> str | None:
    candidate = normalize_space(account)
    if not candidate:
        return None
    if candidate.isdigit():
        return candidate
    match = re.search(r"/u/(\d+)", candidate)
    if match:
        return match.group(1)
    match = re.search(r"uid=(\d+)", candidate)
    if match:
        return match.group(1)
    return None


def normalize_profile_url(account: str) -> str:
    uid = extract_uid(account)
    if uid:
        return f"https://weibo.com/u/{uid}"
    if account.startswith("http://") or account.startswith("https://"):
        return account
    return f"https://s.weibo.com/user?q={account}"


def safe_filename(value: str) -> str:
    return re.sub(r"[<>:\"/\\\\|?*]+", "_", value)


def build_public_download_url(relative_path: Path) -> str:
    normalized = relative_path.as_posix().lstrip("./")
    return f"/downloads/{normalized}"


def split_sentences(text: str) -> list[str]:
    chunks = re.split(r"[。！？!?\n]+", text)
    return [normalize_space(item) for item in chunks if normalize_space(item)]


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        items.append(value)
    return items


def infer_file_extension(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix and len(suffix) <= 5:
        return suffix
    return ".jpg"


def truncate_text(text: str, limit: int = 80) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}…"
