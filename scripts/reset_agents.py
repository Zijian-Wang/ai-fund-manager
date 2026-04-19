"""Wipe agent state and derived records for a fresh run.

Run from the project root:

    python scripts/reset_agents.py                # dry-run, lists what would go
    python scripts/reset_agents.py --confirm      # actually delete

Removes:
  - agents/<name>/portfolio_state.json
  - agents/<name>/trade_journal/
  - agents/<name>/output/
  - track_record/nav_history.json

Preserves by default:
  - memory files (investment_beliefs.md, market_regime.md, watchlist.json,
    lessons/) so the agents keep their accumulated judgment.
  - data_cache/ (market data is expensive to re-fetch).

Pass --also-memory to also wipe memory files, and --also-cache to wipe the
data cache. Both are aggressive; use sparingly.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = ROOT / "agents"
TRACK_RECORD = ROOT / "track_record" / "nav_history.json"
DATA_CACHE = ROOT / "data_cache"

_MEMORY_FILES = {
    "investment_beliefs.md", "market_regime.md", "watchlist.json",
}
_MEMORY_DIRS = {"lessons"}


def _collect(also_memory: bool, also_cache: bool) -> list[Path]:
    targets: list[Path] = []
    if AGENTS_ROOT.exists():
        for agent_dir in sorted(AGENTS_ROOT.iterdir()):
            if not agent_dir.is_dir():
                continue
            state = agent_dir / "portfolio_state.json"
            if state.exists():
                targets.append(state)
            for sub in ("trade_journal", "output"):
                p = agent_dir / sub
                if p.exists():
                    targets.append(p)
            if also_memory:
                for name in _MEMORY_FILES:
                    p = agent_dir / name
                    if p.exists():
                        targets.append(p)
                for name in _MEMORY_DIRS:
                    p = agent_dir / name
                    if p.exists():
                        targets.append(p)
    if TRACK_RECORD.exists():
        targets.append(TRACK_RECORD)
    if also_cache and DATA_CACHE.exists():
        for entry in sorted(DATA_CACHE.iterdir()):
            # Keep trade_cal.json and valid_tickers.json — they're reusable
            # and expensive to refresh.
            if entry.name in {"trade_cal.json", "valid_tickers.json"}:
                continue
            targets.append(entry)
    return targets


def _delete(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm", action="store_true",
                        help="actually delete (default is dry-run)")
    parser.add_argument("--also-memory", action="store_true",
                        help="also wipe agent memory files")
    parser.add_argument("--also-cache", action="store_true",
                        help="also wipe dated data_cache/ subdirs")
    args = parser.parse_args()

    targets = _collect(args.also_memory, args.also_cache)
    if not targets:
        print("nothing to clean")
        return

    verb = "DELETE" if args.confirm else "would delete"
    for t in targets:
        print(f"  {verb} {t.relative_to(ROOT)}")

    if not args.confirm:
        print(f"\n{len(targets)} items — re-run with --confirm to apply.")
        return

    for t in targets:
        _delete(t)
    print(f"\ncleaned {len(targets)} items.")


if __name__ == "__main__":
    main()
