"""Input validation and bar-to-return conversion."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    symbol: str
    close: float
    sector: str


def read_bars(path: str | Path) -> list[Bar]:
    bars: list[Bar] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "symbol", "close", "sector"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"CSV columns must include {sorted(required)}")
        for row in reader:
            close = float(row["close"])
            if close <= 0:
                raise ValueError("close prices must be positive")
            bars.append(
                Bar(
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    symbol=row["symbol"].strip(),
                    close=close,
                    sector=row["sector"].strip(),
                )
            )
    bars.sort(key=lambda bar: (bar.timestamp, bar.symbol))
    return bars


def price_panels(
    bars: list[Bar],
) -> tuple[list[datetime], list[str], dict[str, str], list[dict[str, float]]]:
    sectors: dict[str, str] = {}
    by_time: dict[datetime, dict[str, float]] = {}
    for bar in bars:
        if bar.symbol in sectors and sectors[bar.symbol] != bar.sector:
            raise ValueError(f"sector changed for {bar.symbol}")
        sectors[bar.symbol] = bar.sector
        if bar.symbol in by_time.setdefault(bar.timestamp, {}):
            raise ValueError(f"duplicate bar for {bar.symbol} at {bar.timestamp}")
        by_time[bar.timestamp][bar.symbol] = bar.close
    timestamps = sorted(by_time)
    symbols = sorted(sectors)
    if len(timestamps) < 2 or len(symbols) < 3:
        raise ValueError("at least two timestamps and three symbols are required")
    for timestamp, panel in by_time.items():
        missing = set(symbols) - set(panel)
        if missing:
            raise ValueError(f"missing bars at {timestamp}: {sorted(missing)}")
    return timestamps, symbols, sectors, [by_time[timestamp] for timestamp in timestamps]

