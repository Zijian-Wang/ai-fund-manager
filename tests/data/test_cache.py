"""Tests for cache utilities."""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.data.cache import (
    cache_dir_for,
    is_stale,
    read_json,
    trade_cal_path,
    write_json_atomic,
)


def test_write_json_atomic_creates_file_with_utf8_chinese(tmp_cache_dir: Path) -> None:
    target = tmp_cache_dir / "sub" / "file.json"
    write_json_atomic(target, {"hello": "你好"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"hello": "你好"}


def test_write_json_atomic_overwrites_and_leaves_no_tmp(tmp_cache_dir: Path) -> None:
    target = tmp_cache_dir / "file.json"
    write_json_atomic(target, {"v": 1})
    write_json_atomic(target, {"v": 2})
    assert not (tmp_cache_dir / "file.json.tmp").exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 2}


def test_read_json_returns_none_when_missing(tmp_cache_dir: Path) -> None:
    assert read_json(tmp_cache_dir / "missing.json") is None


def test_read_json_returns_parsed_dict(tmp_cache_dir: Path) -> None:
    target = tmp_cache_dir / "f.json"
    target.write_text(json.dumps({"k": "v"}), encoding="utf-8")
    assert read_json(target) == {"k": "v"}


def test_cache_dir_for_returns_eval_date_subdir(tmp_cache_dir: Path) -> None:
    assert cache_dir_for(tmp_cache_dir, "2026-04-17") == tmp_cache_dir / "2026-04-17"


def test_trade_cal_path_returns_root_level_file(tmp_cache_dir: Path) -> None:
    assert trade_cal_path(tmp_cache_dir) == tmp_cache_dir / "trade_cal.json"


def test_is_stale_true_when_missing(tmp_cache_dir: Path) -> None:
    assert is_stale(tmp_cache_dir / "missing.json", max_age_days=5) is True


def test_is_stale_false_when_fresh(tmp_cache_dir: Path) -> None:
    target = tmp_cache_dir / "fresh.json"
    target.write_text("{}", encoding="utf-8")
    assert is_stale(target, max_age_days=5) is False


def test_is_stale_true_when_old(tmp_cache_dir: Path) -> None:
    target = tmp_cache_dir / "old.json"
    target.write_text("{}", encoding="utf-8")
    old_ts = target.stat().st_mtime - (10 * 86400)
    os.utime(target, (old_ts, old_ts))
    assert is_stale(target, max_age_days=5) is True
