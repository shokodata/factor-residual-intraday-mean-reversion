"""Recent multi-timeframe structural price zones."""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class OHLCV:
    timestamp: datetime; symbol: str; open: float; high: float; low: float; close: float; volume: float


def read_ohlcv(path: str | Path) -> list[OHLCV]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = [OHLCV(datetime.fromisoformat(r["timestamp"]), r["symbol"],
                float(r["open"]), float(r["high"]), float(r["low"]),
                float(r["close"]), float(r["volume"])) for r in csv.DictReader(handle)]
    return sorted(rows, key=lambda x: (x.symbol, x.timestamp))


def _aggregate(rows: list[OHLCV], mode: str) -> list[OHLCV]:
    groups: dict[tuple, list[OHLCV]] = defaultdict(list)
    for row in rows:
        local = row.timestamp
        key = local.date() if mode == "daily" else (local.date(), max(0, (local.hour - 9) // 4))
        groups[key].append(row)
    result = []
    for group in groups.values():
        group.sort(key=lambda x: x.timestamp)
        first, last = group[0], group[-1]
        result.append(OHLCV(last.timestamp, last.symbol, first.open, max(x.high for x in group),
                            min(x.low for x in group), last.close, sum(x.volume for x in group)))
    return sorted(result, key=lambda x: x.timestamp)


def _atr(rows: list[OHLCV]) -> float:
    ranges = [row.high - row.low for row in rows[-14:]]
    return sum(ranges) / len(ranges) if ranges else 0.0


def _pivots(rows: list[OHLCV]) -> Iterable[tuple[float, str, int]]:
    # A pivot is only usable after the following bar has completed.
    for i in range(1, len(rows) - 1):
        if rows[i].low <= min(rows[i-1].low, rows[i+1].low): yield rows[i].low, "SUPPORT", i
        if rows[i].high >= max(rows[i-1].high, rows[i+1].high): yield rows[i].high, "RESISTANCE", i


def analyze_levels(rows: list[OHLCV], price: float) -> dict:
    if len(rows) < 10: return {"status": "INSUFFICIENT_HISTORY"}
    rows = rows[-14 * 7:]
    daily, four = _aggregate(rows, "daily")[-14:], _aggregate(rows, "four")
    width = max(_atr(daily) * .12, price * .002)
    points = []
    for bars, timeframe, weight in ((rows, "1H", 1), (four, "4H", 2), (daily, "1D", 3)):
        for level, kind, index in _pivots(bars):
            recency = 1 + 2 * (index + 1) / len(bars)
            points.append({"price": level, "kind": kind, "timeframe": timeframe,
                           "score": weight * recency})
    zones = []
    for point in sorted(points, key=lambda x: x["price"]):
        zone = next((z for z in zones if abs(z["center"] - point["price"]) <= width), None)
        if zone is None:
            zone = {"center": point["price"], "score": 0.0, "timeframes": set(), "kinds": []}; zones.append(zone)
        zone["score"] += point["score"]; zone["timeframes"].add(point["timeframe"]); zone["kinds"].append(point["kind"])
    for z in zones:
        z["lower"], z["upper"] = z["center"] - width, z["center"] + width
        z["timeframes"] = sorted(z["timeframes"]); z["kind"] = max(set(z["kinds"]), key=z["kinds"].count); del z["kinds"]
    support = max((z for z in zones if z["kind"] == "SUPPORT" and z["center"] <= price), key=lambda z:z["center"], default=None)
    resistance = min((z for z in zones if z["kind"] == "RESISTANCE" and z["center"] >= price), key=lambda z:z["center"], default=None)
    return {"status":"READY", "support":support, "resistance":resistance, "zone_width":width}


def annotate_candidates(candidates: list[dict], rows: list[OHLCV]) -> list[dict]:
    by_symbol: dict[str, list[OHLCV]] = defaultdict(list)
    for row in rows: by_symbol[row.symbol].append(row)
    for candidate in candidates:
        history = by_symbol.get(candidate["symbol"], [])
        if not history: candidate["level_confluence"] = {"status":"INSUFFICIENT_HISTORY"}; continue
        price = history[-1].close; levels = analyze_levels(history, price)
        is_long = candidate["direction"] == "LONG"
        relevant = levels.get("support") if is_long else levels.get("resistance")
        opposing = levels.get("resistance") if is_long else levels.get("support")
        aligned = bool(relevant and relevant["lower"] <= price <= relevant["upper"])
        target = (opposing["lower"] if is_long else opposing["upper"]) if opposing else None
        invalidation = None
        if relevant:
            invalidation = relevant["lower"] - levels["zone_width"] * .25 if is_long else relevant["upper"] + levels["zone_width"] * .25
        room = ((target - price) / price if is_long else (price - target) / price) if target else None
        candidate["level_confluence"] = {**levels, "price":price, "aligned":aligned, "relevant_zone":relevant,
            "reaction_price": relevant["center"] if relevant else None,
            "target_price": target, "target_room": room, "invalidation_price": invalidation,
            "confluence_score": relevant["score"] if aligned else 0.0}
    return sorted(candidates, key=lambda c:(c["level_confluence"].get("aligned",False), c["level_confluence"].get("confluence_score",0), abs(c["residual_zscore"])), reverse=True)
