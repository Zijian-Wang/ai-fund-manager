"""Manual smoke test for the data layer.

Usage (from repo root):
    .venv/bin/python scripts/smoke_data.py [--holdings 300750.SZ,000001.SZ]

Refreshes the trading calendar, resolves eval_date, fetches market data
+ news, dumps everything to ``data_cache/{eval_date}/``, prints a summary.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure repo root is on sys.path so `src.*` imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.data.akshare_client import AKShareClient
from src.data.baostock_client import BaoStockClient
from src.data.eval_date import resolve_eval_date
from src.data.market_data import fetch_market_data
from src.data.news_fetcher import fetch_news
from src.data.tushare_client import TuShareClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the data layer.")
    parser.add_argument(
        "--holdings",
        default="300750.SZ",
        help="Comma-separated TuShare ticker codes to fetch.",
    )
    args = parser.parse_args()

    load_dotenv()
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        raise SystemExit("TUSHARE_TOKEN missing — set it in .env")

    cache_root = Path("data_cache")
    cache_root.mkdir(exist_ok=True)

    print("==> Initializing clients")
    tushare = TuShareClient(token=token, cache_root=cache_root)
    akshare = AKShareClient()
    baostock = BaoStockClient()

    print("==> Refreshing trading calendar")
    today = date.today()
    start = today.replace(month=1, day=1).strftime("%Y%m%d")
    end = (today + timedelta(days=60)).strftime("%Y%m%d")
    tushare.trade_cal_refresh(start_date=start, end_date=end)

    print("==> Resolving eval_date")
    eval_date = resolve_eval_date(cache_root=cache_root)
    print(f"    eval_date = {eval_date}")

    holdings = [t.strip() for t in args.holdings.split(",") if t.strip()]
    print(f"==> Fetching market data (holdings: {holdings})")
    market = fetch_market_data(
        eval_date=eval_date,
        holdings_tickers=holdings,
        cache_root=cache_root,
        tushare=tushare,
        akshare=akshare,
        baostock=baostock,
    )

    print(f"    indices       :")
    for code, block in market["indices"].items():
        print(f"      {code}: source={block['source']}, rows={len(block['rows'])}")
    print(f"    sector ranking: source={market['sector_ranking']['source']}, "
          f"rows={len(market['sector_ranking']['rows'])}")
    print(f"    northbound    : source={market['northbound']['source']}, "
          f"rows={len(market['northbound']['rows'])}")
    print(f"    holdings      :")
    for code, block in market["holdings"].items():
        print(f"      {code}: source={block['source']}, rows={len(block['rows'])}")
    if market["errors"]:
        print(f"    errors        :")
        for err in market["errors"]:
            print(f"      - {err}")

    print("==> Fetching news")
    news = fetch_news(limit=20)
    print(f"    {len(news)} headlines fetched")
    for item in news[:5]:
        print(f"    [{item['source']}] {item['title']}")

    print(f"==> Done. Cache written to {cache_root / eval_date}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
