"""News fetcher: structured news from Eastmoney + 财联社.

Each fetcher returns a list of normalized dicts:
    {"title": str, "summary": str, "source": str, "timestamp": str}

Failures return an empty list — news is supplementary; agents can decide
without it. ``fetch_news()`` merges both sources and deduplicates by title.

Endpoints (probe-validated 2026-04):
- Eastmoney: https://np-listapi.eastmoney.com/comm/web/getFastNewsList
  payload at data.fastNewsList[*]
- 财联社:    https://www.cls.cn/nodeapi/telegraphList
  payload at data.roll_data[*]
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests


_EASTMONEY_URL = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
_CAIXIN_URL = "https://www.cls.cn/nodeapi/telegraphList"
_DEFAULT_TIMEOUT = 10
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Referer": "https://finance.eastmoney.com/",
}


def fetch_eastmoney(*, limit: int = 20) -> list[dict]:
    """Fetch latest market 快讯 from Eastmoney."""
    try:
        resp = requests.get(
            _EASTMONEY_URL,
            headers=_HEADERS,
            params={
                "client": "web",
                "biz": "web_724hour",
                "fastColumn": "102",
                "sortEnd": "",
                "pageSize": limit,
                "req_trace": "",
            },
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:  # noqa: BLE001 — news is supplementary
        return []

    raw_items = (
        payload.get("data", {}).get("fastNewsList", [])
        if isinstance(payload, dict)
        else []
    )
    out: list[dict] = []
    for item in raw_items[:limit]:
        if not isinstance(item, dict) or "title" not in item:
            continue
        out.append(
            {
                "title": (item.get("title") or "").strip(),
                "summary": (item.get("summary") or "").strip(),
                "source": "eastmoney",
                "timestamp": item.get("showTime", ""),
            }
        )
    return out


def fetch_caixin(*, limit: int = 20) -> list[dict]:
    """Fetch latest 财联社 telegraph items."""
    try:
        resp = requests.get(
            _CAIXIN_URL,
            headers=_HEADERS,
            params={"refresh_type": 1, "rn": limit, "last_time": ""},
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return []

    raw_items = (
        payload.get("data", {}).get("roll_data", [])
        if isinstance(payload, dict)
        else []
    )
    out: list[dict] = []
    for item in raw_items[:limit]:
        if not isinstance(item, dict) or "title" not in item:
            continue
        ctime = item.get("ctime")
        if isinstance(ctime, (int, float)):
            timestamp = datetime.fromtimestamp(int(ctime), tz=timezone.utc).isoformat()
        else:
            timestamp = str(ctime or "")
        out.append(
            {
                "title": (item.get("title") or "").strip(),
                "summary": (item.get("brief") or item.get("content") or "").strip(),
                "source": "caixin",
                "timestamp": timestamp,
            }
        )
    return out


def fetch_news(*, limit: int = 30) -> list[dict]:
    """Fetch + merge + dedupe news. Eastmoney first, then 财联社 not-already-seen."""
    eastmoney_items = fetch_eastmoney(limit=limit)
    caixin_items = fetch_caixin(limit=limit)
    seen = {item["title"] for item in eastmoney_items}
    merged = list(eastmoney_items)
    for item in caixin_items:
        if item["title"] not in seen:
            merged.append(item)
            seen.add(item["title"])
    return merged[:limit]
