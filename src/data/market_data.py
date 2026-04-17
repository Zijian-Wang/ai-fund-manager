"""Market data orchestrator.

Fetches indices, sector rankings, northbound flow, and per-holdings prices
through a primary -> fallback -> cache cascade. Each piece is cached to
``data_cache/{eval_date}/<name>.json`` on success.

Per probe-validated design:
- Index / stock: TuShare -> BaoStock -> cache
- Sector ranking: AKShare -> cache (no fallback source — only AKShare provides this)
- Northbound: TuShare -> cache (AKShare's northbound endpoints are
  unreachable from our environment; dropped)
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.data.cache import cache_dir_for, is_stale, read_json, write_json_atomic


INDICES = ("000001.SH", "399001.SZ", "399006.SZ", "000300.SH")

# stock_basic refreshes weekly — TuShare's listed-stock list changes rarely
_TICKER_CACHE_MAX_AGE_DAYS = 7

# Lookback window for "last 5 trading days" — fetch 12 calendar days to
# cover weekends + holidays.
_LOOKBACK_DAYS = 12


def _yyyymmdd(s: str) -> str:
    return s.replace("-", "")


def _start_yyyymmdd(eval_date: str) -> str:
    return (date.fromisoformat(eval_date) - timedelta(days=_LOOKBACK_DAYS)).strftime(
        "%Y%m%d"
    )


def _start_dash(eval_date: str) -> str:
    return (date.fromisoformat(eval_date) - timedelta(days=_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%d"
    )


def _ts_to_baostock_code(ts_code: str) -> str:
    """``000300.SH`` -> ``sh.000300``; ``300750.SZ`` -> ``sz.300750``."""
    code, suffix = ts_code.split(".")
    return f"{suffix.lower()}.{code}"


def fetch_index_5d(
    *,
    ts_code: str,
    eval_date: str,
    cache_root: Path,
    tushare: Any,
    baostock: Any,
) -> dict:
    cache_path = cache_dir_for(cache_root, eval_date) / f"index_{ts_code}.json"
    errors: list[str] = []

    try:
        df = tushare.index_daily(
            ts_code=ts_code,
            start_date=_start_yyyymmdd(eval_date),
            end_date=_yyyymmdd(eval_date),
        )
        result = {"source": "tushare", "rows": df.to_dict(orient="records")}
        write_json_atomic(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"tushare: {exc}")

    try:
        rows = baostock.index_daily(
            code=_ts_to_baostock_code(ts_code),
            start_date=_start_dash(eval_date),
            end_date=eval_date,
        )
        result = {"source": "baostock", "rows": rows}
        write_json_atomic(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"baostock: {exc}")

    cached = read_json(cache_path)
    if cached is not None:
        return {"source": "cache", "rows": cached["rows"]}

    return {"source": "error", "rows": [], "error": "; ".join(errors)}


def fetch_stock_5d(
    *,
    ts_code: str,
    eval_date: str,
    cache_root: Path,
    tushare: Any,
    baostock: Any,
) -> dict:
    cache_path = cache_dir_for(cache_root, eval_date) / f"stock_{ts_code}.json"
    errors: list[str] = []

    try:
        df = tushare.daily(
            ts_code=ts_code,
            start_date=_start_yyyymmdd(eval_date),
            end_date=_yyyymmdd(eval_date),
        )
        result = {"source": "tushare", "rows": df.to_dict(orient="records")}
        write_json_atomic(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"tushare: {exc}")

    try:
        rows = baostock.stock_daily(
            code=_ts_to_baostock_code(ts_code),
            start_date=_start_dash(eval_date),
            end_date=eval_date,
        )
        result = {"source": "baostock", "rows": rows}
        write_json_atomic(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001
        errors.append(f"baostock: {exc}")

    cached = read_json(cache_path)
    if cached is not None:
        return {"source": "cache", "rows": cached["rows"]}

    return {"source": "error", "rows": [], "error": "; ".join(errors)}


def fetch_sector_ranking(
    *,
    eval_date: str,
    cache_root: Path,
    akshare: Any,
) -> dict:
    cache_path = cache_dir_for(cache_root, eval_date) / "sector_ranking.json"
    try:
        rows = akshare.sector_ranking()
        result = {"source": "akshare", "rows": rows}
        write_json_atomic(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001
        cached = read_json(cache_path)
        if cached is not None:
            return {"source": "cache", "rows": cached["rows"]}
        return {"source": "error", "rows": [], "error": f"akshare: {exc}"}


def fetch_northbound_5d(
    *,
    eval_date: str,
    cache_root: Path,
    tushare: Any,
) -> dict:
    cache_path = cache_dir_for(cache_root, eval_date) / "northbound.json"
    try:
        df = tushare.moneyflow_hsgt(
            start_date=_start_yyyymmdd(eval_date),
            end_date=_yyyymmdd(eval_date),
        )
        result = {"source": "tushare", "rows": df.to_dict(orient="records")}
        write_json_atomic(cache_path, result)
        return result
    except Exception as exc:  # noqa: BLE001
        cached = read_json(cache_path)
        if cached is not None:
            return {"source": "cache", "rows": cached["rows"]}
        return {"source": "error", "rows": [], "error": f"tushare: {exc}"}


def get_valid_tickers(*, cache_root: Path, tushare: Any) -> set[str]:
    """Return the set of valid 6-digit ticker codes for guardrail validation.

    Cached at ``data_cache/stock_basic.json`` (root level, not eval_date-keyed —
    the listed-stock list changes rarely). Refreshed weekly.
    """
    from datetime import datetime

    cache_path = Path(cache_root) / "stock_basic.json"
    if not is_stale(cache_path, max_age_days=_TICKER_CACHE_MAX_AGE_DAYS):
        cached = read_json(cache_path)
        if cached is not None:
            return set(cached.get("tickers", []))

    df = tushare.stock_basic()
    tickers = sorted({str(row["symbol"]) for _, row in df.iterrows()})
    write_json_atomic(
        cache_path,
        {"refreshed": datetime.now().isoformat(timespec="seconds"), "tickers": tickers},
    )
    return set(tickers)


def fetch_market_data(
    *,
    eval_date: str,
    holdings_tickers: list[str],
    cache_root: Path,
    tushare: Any,
    akshare: Any,
    baostock: Any,
) -> dict:
    """Top-level orchestrator. Returns a unified market data dict.

    Shape:
        {
          "eval_date": "YYYY-MM-DD",
          "indices": {"000300.SH": {source, rows}, ...},
          "sector_ranking": {source, rows},
          "northbound": {source, rows},
          "holdings": {"300750.SZ": {source, rows}, ...},
          "errors": ["index_000001.SH: ...", ...]
        }
    """
    errors: list[str] = []

    indices: dict[str, dict] = {}
    for ts_code in INDICES:
        block = fetch_index_5d(
            ts_code=ts_code,
            eval_date=eval_date,
            cache_root=cache_root,
            tushare=tushare,
            baostock=baostock,
        )
        indices[ts_code] = block
        if block["source"] == "error":
            errors.append(f"index_{ts_code}: {block['error']}")

    sector = fetch_sector_ranking(
        eval_date=eval_date, cache_root=cache_root, akshare=akshare
    )
    if sector["source"] == "error":
        errors.append(f"sector_ranking: {sector['error']}")

    northbound = fetch_northbound_5d(
        eval_date=eval_date, cache_root=cache_root, tushare=tushare
    )
    if northbound["source"] == "error":
        errors.append(f"northbound: {northbound['error']}")

    holdings: dict[str, dict] = {}
    for ts_code in holdings_tickers:
        block = fetch_stock_5d(
            ts_code=ts_code,
            eval_date=eval_date,
            cache_root=cache_root,
            tushare=tushare,
            baostock=baostock,
        )
        holdings[ts_code] = block
        if block["source"] == "error":
            errors.append(f"stock_{ts_code}: {block['error']}")

    return {
        "eval_date": eval_date,
        "indices": indices,
        "sector_ranking": sector,
        "northbound": northbound,
        "holdings": holdings,
        "errors": errors,
    }


def extract_stock_prices(market_data: dict) -> dict[str, float]:
    """Return {six_digit_symbol: latest_close} from market_data.holdings."""
    out: dict[str, float] = {}
    for ts_code, block in (market_data.get("holdings") or {}).items():
        rows = block.get("rows") or []
        if not rows:
            continue
        close = rows[0].get("close")
        if close is None:
            continue
        try:
            out[ts_code.split(".")[0]] = float(close)
        except (TypeError, ValueError):
            pass
    return out


def extract_index_close(market_data: dict, ts_code: str) -> float | None:
    """Return the latest close for ``ts_code`` (e.g. '000300.SH'), or None."""
    block = (market_data.get("indices") or {}).get(ts_code)
    if not block:
        return None
    rows = block.get("rows") or []
    if not rows:
        return None
    close = rows[0].get("close")
    if close is None:
        return None
    try:
        return float(close)
    except (TypeError, ValueError):
        return None


def extract_stock_volumes_yuan(market_data: dict) -> dict[str, float]:
    """Return {six_digit_symbol: latest_daily_amount_in_yuan}.

    TuShare's ``amount`` column is in 千元; we multiply by 1000 to get ¥.
    Skips tickers where amount is absent (e.g. BaoStock fallback rows
    without amount). Orchestrator passes this to guardrails to enforce
    the min_volume rule.
    """
    out: dict[str, float] = {}
    for ts_code, block in (market_data.get("holdings") or {}).items():
        rows = block.get("rows") or []
        if not rows:
            continue
        amount = rows[0].get("amount")
        if amount is None:
            continue
        try:
            out[ts_code.split(".")[0]] = float(amount) * 1000
        except (TypeError, ValueError):
            pass
    return out
