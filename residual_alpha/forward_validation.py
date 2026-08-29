"""Persistent forward validation for residual-alpha paper signals."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import read_bars, price_panels

EASTERN = ZoneInfo("America/New_York")
HORIZONS_MINUTES = (15, 30, 60, 120)
LEDGER_PATH = Path("forward_validation.json")
COST_BPS = 1.0


def _load(path: str | Path = LEDGER_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {"schema_version": 1, "signals": []}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _save(payload: dict, path: str | Path = LEDGER_PATH) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")


def _portfolio_return(signal: dict, entry_prices: dict[str, float], prices: dict[str, float]) -> float | None:
    legs = {
        signal["symbol"]: signal["stock_weight"],
        "SPY": signal["spy_weight"],
        signal["sector_etf"]: signal["sector_etf_weight"],
    }
    if any(symbol not in entry_prices or symbol not in prices for symbol in legs):
        return None
    gross_return = sum(
        weight * (prices[symbol] / entry_prices[symbol] - 1.0)
        for symbol, weight in legs.items()
    )
    gross_notional = sum(abs(weight) for weight in legs.values())
    round_trip_cost = 2.0 * gross_notional * COST_BPS / 10_000.0
    return gross_return - round_trip_cost


def _first_panel_at_or_after(timestamps, panels, target, same_date):
    for timestamp, panel in zip(timestamps, panels):
        local = timestamp.astimezone(EASTERN)
        if local.date() == same_date and timestamp >= target:
            return timestamp, panel
    return None, None


def _eod_panel(timestamps, panels, same_date):
    chosen = None
    for timestamp, panel in zip(timestamps, panels):
        local = timestamp.astimezone(EASTERN)
        if local.date() != same_date:
            continue
        if local.time() <= time(15, 50):
            chosen = (timestamp, panel)
    return chosen if chosen else (None, None)


def update_forward_validation(report_path: str | Path, bars_path: str | Path, ledger_path: str | Path = LEDGER_PATH) -> dict:
    with Path(report_path).open(encoding="utf-8") as handle:
        report = json.load(handle)
    bars = read_bars(bars_path)
    timestamps, _, _, panels = price_panels(bars)
    ledger = _load(ledger_path)
    signals = ledger.setdefault("signals", [])
    existing = {signal["signal_id"]: signal for signal in signals}

    as_of = datetime.fromisoformat(report["as_of"])
    latest_panel = panels[-1]
    latest_candidates = report.get("latest_candidates", [])

    completed_by_key = {
        (trade["symbol"], trade["entry_time"]): trade
        for trade in report.get("trades", [])
    }
    state_trade = report.get("current_state", {}).get("trade")
    if state_trade:
        completed_by_key.setdefault((state_trade["symbol"], state_trade["entry_time"]), state_trade)

    for candidate in latest_candidates:
        signal_id = f"{as_of.isoformat()}::{candidate['symbol']}"
        signal = existing.get(signal_id)
        if signal is None:
            signal = {
                "signal_id": signal_id,
                "signal_time": as_of.isoformat(),
                "symbol": candidate["symbol"],
                "sector": candidate["sector"],
                "direction": candidate["direction"],
                "entry_residual_z": candidate["residual_zscore"],
                "stock_weight": candidate["stock_weight"],
                "spy_weight": candidate["spy_weight"],
                "sector_etf": candidate["sector_etf"],
                "sector_etf_weight": candidate["sector_etf_weight"],
                "entry_prices": {
                    candidate["symbol"]: latest_panel.get(candidate["symbol"]),
                    "SPY": latest_panel.get("SPY"),
                    candidate["sector_etf"]: latest_panel.get(candidate["sector_etf"]),
                },
                "selected_paper_entry": False,
                "trade_outcome": None,
                "horizons": {},
            }
            signals.append(signal)
            existing[signal_id] = signal

    # Mark the mechanically selected entry when its entry timestamp/symbol matches a recorded candidate.
    for signal in signals:
        key = (signal["symbol"], signal["signal_time"])
        trade = completed_by_key.get(key)
        if trade:
            signal["selected_paper_entry"] = True
            signal["trade_outcome"] = {
                "exit_time": trade.get("exit_time"),
                "exit_z": trade.get("exit_z"),
                "exit_reason": trade.get("exit_reason"),
                "holding_bars": trade.get("holding_bars", 0),
                "net_return": trade.get("net_return", 0.0),
                "resolved": bool(trade.get("exit_time")),
            }

    # Populate fixed forward horizons for every observed qualifying candidate.
    for signal in signals:
        entry_time = datetime.fromisoformat(signal["signal_time"])
        local_date = entry_time.astimezone(EASTERN).date()
        entry_prices = signal.get("entry_prices", {})
        if not all(value for value in entry_prices.values()):
            continue
        for minutes in HORIZONS_MINUTES:
            label = f"{minutes}m"
            if label in signal["horizons"]:
                continue
            target = entry_time + timedelta(minutes=minutes)
            timestamp, panel = _first_panel_at_or_after(timestamps, panels, target, local_date)
            if panel is not None:
                signal["horizons"][label] = {
                    "timestamp": timestamp.isoformat(),
                    "net_fixed_weight_return": _portfolio_return(signal, entry_prices, panel),
                }
        if "EOD" not in signal["horizons"]:
            timestamp, panel = _eod_panel(timestamps, panels, local_date)
            if timestamp is not None and timestamp > entry_time:
                signal["horizons"]["EOD"] = {
                    "timestamp": timestamp.isoformat(),
                    "net_fixed_weight_return": _portfolio_return(signal, entry_prices, panel),
                }

    ledger["updated_at"] = datetime.now().astimezone().isoformat()
    _save(ledger, ledger_path)
    return build_summary(ledger)


def build_summary(ledger: dict | None = None) -> dict:
    ledger = ledger or _load()
    signals = ledger.get("signals", [])
    selected = [signal for signal in signals if signal.get("selected_paper_entry")]
    resolved = [signal for signal in selected if (signal.get("trade_outcome") or {}).get("resolved")]
    converged = [signal for signal in resolved if signal["trade_outcome"].get("exit_reason") == "CONVERGED"]

    horizon_summary = {}
    for label in ["15m", "30m", "60m", "120m", "EOD"]:
        values = [
            signal["horizons"][label]["net_fixed_weight_return"]
            for signal in signals
            if label in signal.get("horizons", {})
            and signal["horizons"][label]["net_fixed_weight_return"] is not None
        ]
        horizon_summary[label] = {
            "observations": len(values),
            "average_return": sum(values) / len(values) if values else None,
            "positive_rate": sum(value > 0 for value in values) / len(values) if values else None,
        }

    return {
        "qualifying_candidates": len(signals),
        "selected_paper_entries": len(selected),
        "resolved_paper_entries": len(resolved),
        "converged_paper_entries": len(converged),
        "paper_entry_convergence_rate": len(converged) / len(resolved) if resolved else None,
        "horizons": horizon_summary,
    }
