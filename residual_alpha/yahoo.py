"""Yahoo Finance adapter used by the scheduled research workflow."""

from __future__ import annotations

import csv
from pathlib import Path


def read_universe(path: str | Path) -> dict[str, str]:
    universe: dict[str, str] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"symbol", "sector"}.issubset(reader.fieldnames):
            raise ValueError("universe CSV must contain symbol and sector columns")
        for row in reader:
            symbol = row["symbol"].strip().upper()
            sector = row["sector"].strip()
            if not symbol or not sector:
                raise ValueError("universe symbols and sectors cannot be empty")
            if symbol in universe:
                raise ValueError(f"duplicate universe symbol: {symbol}")
            universe[symbol] = sector
    if len(universe) < 10 or len(set(universe.values())) < 2:
        raise ValueError("universe must contain at least 10 symbols across two sectors")
    return universe


def download_bars(
    universe_path: str | Path,
    output_path: str | Path,
    period: str = "60d",
    interval: str = "5m",
) -> tuple[int, int]:
    """Download a complete adjusted-close panel and write engine-format CSV."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Install the project dependencies before downloading data") from exc

    universe = read_universe(universe_path)
    symbols = list(universe)
    frame = yf.download(
        symbols,
        period=period,
        interval=interval,
        auto_adjust=True,
        prepost=False,
        group_by="column",
        threads=True,
        progress=False,
        timeout=30,
    )
    if frame.empty:
        raise RuntimeError("Yahoo Finance returned no data")
    closes = frame["Close"]
    if getattr(closes, "ndim", 1) != 2:
        raise RuntimeError("Yahoo Finance returned an unexpected close-price layout")
    missing_symbols = set(symbols) - set(closes.columns)
    if missing_symbols:
        raise RuntimeError(f"Yahoo Finance omitted symbols: {sorted(missing_symbols)}")

    # The backtester requires a synchronous panel. Keeping only timestamps with
    # every symbol avoids forward-filling stale prices into alpha signals.
    closes = closes[symbols].dropna(how="any")
    if len(closes) < 100:
        raise RuntimeError(f"only {len(closes)} complete bars were returned")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "symbol", "close", "sector"])
        for timestamp, row in closes.iterrows():
            iso_timestamp = timestamp.isoformat()
            for symbol in symbols:
                writer.writerow([iso_timestamp, symbol, f"{float(row[symbol]):.8f}", universe[symbol]])
    return len(closes), len(symbols)

