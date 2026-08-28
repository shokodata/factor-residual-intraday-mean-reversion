"""Deterministic synthetic panel for smoke tests and demonstrations."""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path


def generate(path: str | Path, bars: int = 500, seed: int = 7) -> None:
    random.seed(seed)
    sectors = {**{f"TECH{i}": "Technology" for i in range(4)}, **{f"FIN{i}": "Financials" for i in range(4)}}
    prices = {symbol: 100.0 for symbol in sectors}
    residual_state = {symbol: 0.0 for symbol in sectors}
    start = datetime(2025, 1, 2, 9, 30)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "symbol", "close", "sector"])
        for step in range(bars):
            timestamp = start + timedelta(minutes=5 * step)
            market = random.gauss(0.0, 0.0007)
            sector_moves = {
                "Technology": market + random.gauss(0.0, 0.00045),
                "Financials": market + random.gauss(0.0, 0.00045),
            }
            for offset, (symbol, sector) in enumerate(sectors.items()):
                shock = random.gauss(0.0, 0.0012)
                # Negative autocorrelation creates a deliberately mean-reverting
                # residual process; this validates mechanics, not profitability.
                residual_state[symbol] = -0.55 * residual_state[symbol] + shock
                move = (0.8 + offset * 0.03) * market + 0.65 * sector_moves[sector] + residual_state[symbol]
                prices[symbol] *= math.exp(move)
                writer.writerow([timestamp.isoformat(), symbol, f"{prices[symbol]:.8f}", sector])
