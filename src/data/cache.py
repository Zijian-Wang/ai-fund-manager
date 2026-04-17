"""Disk cache utilities for the data layer.

Layout:
    data_cache/
        trade_cal.json              # trading calendar (eval_date independent)
        {YYYY-MM-DD}/               # one dir per evaluation date
            *.json                  # market data, news
            briefing.md             # frozen briefing (Phase 2 writes this)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def cache_dir_for(cache_root: Path, eval_date: str) -> Path:
    return Path(cache_root) / eval_date


def trade_cal_path(cache_root: Path) -> Path:
    return Path(cache_root) / "trade_cal.json"


def write_json_atomic(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> Any | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def is_stale(path: Path, max_age_days: int) -> bool:
    path = Path(path)
    if not path.exists():
        return True
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds > (max_age_days * 86400)
