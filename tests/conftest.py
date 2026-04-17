"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    """An isolated cache directory for the duration of a test."""
    cache = tmp_path / "data_cache"
    cache.mkdir()
    return cache
