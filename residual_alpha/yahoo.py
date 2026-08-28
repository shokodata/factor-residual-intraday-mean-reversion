"""Yahoo Finance adapter used by the scheduled research workflow."""

from __future__ import annotations

import csv
from pathlib import Path
from time import sleep


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
    batch_size: int = 50,
) -> tuple[int, int]:
    """Download a complete adjusted-close panel and write engine-format CSV."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Install the project dependencies before downloading data") from exc

    universe = read_universe(universe_path)
    symbols = list(universe)
    if batch_size < 10 or batch_size > 100:
        raise ValueError("batch_size must be between 10 and 100")
    close_batches = []
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        frame = yf.download(
            batch,
            period=period,
            interval=interval,
            auto_adjust=True,
            prepost=False,
            group_by="column",
            threads=True,
            progress=False,
            timeout=30,
        )
        if frame.empty or "Close" not in frame:
            raise RuntimeError(f"Yahoo Finance returned no data for batch starting {batch[0]}")
        closes = frame["Close"]
        if getattr(closes, "ndim", 1) != 2:
            raise RuntimeError("Yahoo Finance returned an unexpected close-price layout")
        close_batches.append(closes)
        if start + batch_size < len(symbols):
            sleep(0.4)

    import pandas as pd

    closes = pd.concat(close_batches, axis=1)
    closes = closes.loc[:, ~closes.columns.duplicated()]
    returned = [symbol for symbol in symbols if symbol in closes.columns]
    if len(returned) < max(10, int(len(symbols) * 0.95)):
        raise RuntimeError(f"Yahoo Finance returned only {len(returned)} of {len(symbols)} symbols")
    closes = closes[returned].sort_index()
    if len(closes) < 2:
        raise RuntimeError("Yahoo Finance returned too few timestamps")
    # Yahoo can expose the currently forming interval (and occasionally label it
    # with the interval end). Never generate an entry from a partial final bar.
    closes = closes.iloc[:-1]

    # Fill at most one isolated five-minute gap, then retain only stocks with a
    # complete synchronous panel. Broad or current missingness is never filled.
    closes = closes.groupby(closes.index.date).ffill(limit=1)
    closes = closes.dropna(axis=1, how="any")
    symbols = [symbol for symbol in symbols if symbol in closes.columns]
    closes = closes[symbols].dropna(how="any")
    if len(symbols) < int(len(universe) * 0.90):
        raise RuntimeError(f"only {len(symbols)} of {len(universe)} symbols passed completeness checks")
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
