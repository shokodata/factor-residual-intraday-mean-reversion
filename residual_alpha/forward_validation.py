"""Persistent forward validation for residual-alpha paper signals."""

from __future__ import annotations

import json
import math
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
        return {"schema_version": 2, "signals": []}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _save(payload: dict, path: str | Path = LEDGER_PATH) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")


def _normalize_time(value: str) -> str:
    return datetime.fromisoformat(value).isoformat()


def _mean(values):
    return sum(values) / len(values) if values else None


def _std(values):
    if len(values) < 2:
        return 0.0
    center = sum(values) / len(values)
    return math.sqrt(sum((value - center) ** 2 for value in values) / (len(values) - 1))


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


def _z_bucket(value: float) -> str:
    value = abs(value)
    if value < 2.0:
        return "1.5-2.0"
    if value < 2.5:
        return "2.0-2.5"
    if value < 3.0:
        return "2.5-3.0"
    if value < 4.0:
        return "3.0-4.0"
    return "4.0-5.0"


def _time_bucket(timestamp: datetime) -> str:
    local = timestamp.astimezone(EASTERN).time()
    if local < time(11, 0):
        return "10:00-11:00"
    if local < time(12, 0):
        return "11:00-12:00"
    if local < time(13, 0):
        return "12:00-13:00"
    if local < time(14, 0):
        return "13:00-14:00"
    return "14:00-14:30"


def _regime_context(timestamps, panels, signal_time, sector_etf):
    prior = [
        (timestamp, panel)
        for timestamp, panel in zip(timestamps, panels)
        if timestamp <= signal_time
        and timestamp >= signal_time - timedelta(minutes=60)
        and timestamp.astimezone(EASTERN).date() == signal_time.astimezone(EASTERN).date()
    ]
    if len(prior) < 2 or "SPY" not in prior[0][1] or "SPY" not in prior[-1][1]:
        return {}

    spy_returns = []
    sector_returns = []
    for (_, previous), (_, current) in zip(prior, prior[1:]):
        if "SPY" in previous and "SPY" in current:
            spy_returns.append(current["SPY"] / previous["SPY"] - 1.0)
        if sector_etf in previous and sector_etf in current:
            sector_returns.append(current[sector_etf] / previous[sector_etf] - 1.0)

    spy_60m_return = prior[-1][1]["SPY"] / prior[0][1]["SPY"] - 1.0
    spy_5m_vol = _std(spy_returns)
    sector_5m_vol = _std(sector_returns)
    noise_scale = spy_5m_vol * math.sqrt(max(len(spy_returns), 1))
    if noise_scale == 0 or abs(spy_60m_return) < noise_scale:
        market_regime = "RANGE"
    elif spy_60m_return > 0:
        market_regime = "UPTREND"
    else:
        market_regime = "DOWNTREND"

    return {
        "spy_60m_return": spy_60m_return,
        "spy_5m_realized_vol": spy_5m_vol,
        "sector_5m_realized_vol": sector_5m_vol,
        "market_regime": market_regime,
    }


def update_forward_validation(report_path: str | Path, bars_path: str | Path, ledger_path: str | Path = LEDGER_PATH) -> dict:
    with Path(report_path).open(encoding="utf-8") as handle:
        report = json.load(handle)
    bars = read_bars(bars_path)
    timestamps, _, _, panels = price_panels(bars)
    panel_by_time = {timestamp.isoformat(): panel for timestamp, panel in zip(timestamps, panels)}
    ledger = _load(ledger_path)
    ledger["schema_version"] = 2
    signals = ledger.setdefault("signals", [])
    existing = {signal["signal_id"]: signal for signal in signals}

    completed_by_key = {
        (trade["symbol"], _normalize_time(trade["entry_time"])): trade
        for trade in report.get("trades", [])
    }
    state_trade = report.get("current_state", {}).get("trade")
    if state_trade:
        completed_by_key.setdefault(
            (state_trade["symbol"], _normalize_time(state_trade["entry_time"])),
            state_trade,
        )

    diagnostics = {
        (item["symbol"], _normalize_time(item["signal_time"])): item
        for item in report.get("forward_diagnostics", [])
    }

    # Ingest every qualifying decision-bar candidate contained in the rolling research report.
    candidate_events = report.get("candidate_events") or []
    if not candidate_events:
        # Backward-compatible fallback for reports created before diagnostic event capture.
        as_of = datetime.fromisoformat(report["as_of"])
        latest = [
            {"signal_time": as_of.isoformat(), **candidate}
            for candidate in report.get("latest_candidates", [])
        ]
        candidate_events = latest

    for candidate in candidate_events:
        signal_time = datetime.fromisoformat(candidate["signal_time"])
        signal_time_text = signal_time.isoformat()
        signal_id = f"{signal_time_text}::{candidate['symbol']}"
        panel = panel_by_time.get(signal_time_text)
        if panel is None:
            continue
        signal = existing.get(signal_id)
        if signal is None:
            signal = {
                "signal_id": signal_id,
                "signal_time": signal_time_text,
                "symbol": candidate["symbol"],
                "sector": candidate["sector"],
                "direction": candidate["direction"],
                "entry_residual_z": candidate["residual_zscore"],
                "z_bucket": _z_bucket(candidate["residual_zscore"]),
                "time_bucket": _time_bucket(signal_time),
                "stock_weight": candidate["stock_weight"],
                "spy_weight": candidate["spy_weight"],
                "sector_etf": candidate["sector_etf"],
                "sector_etf_weight": candidate["sector_etf_weight"],
                "entry_prices": {
                    candidate["symbol"]: panel.get(candidate["symbol"]),
                    "SPY": panel.get("SPY"),
                    candidate["sector_etf"]: panel.get(candidate["sector_etf"]),
                },
                "market_context": _regime_context(timestamps, panels, signal_time, candidate["sector_etf"]),
                "selected_paper_entry": False,
                "trade_outcome": None,
                "horizons": {},
                "path_stats": {"mfe": None, "mae": None, "time_to_convergence_minutes": None},
                "residual_path": [],
            }
            signals.append(signal)
            existing[signal_id] = signal

    # Mark mechanically selected entries and copy exact trade outcomes.
    for signal in signals:
        key = (signal["symbol"], _normalize_time(signal["signal_time"]))
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

        diagnostic = diagnostics.get(key)
        if diagnostic:
            signal["residual_path"] = diagnostic.get("residual_path", [])
            signal.setdefault("path_stats", {})["time_to_convergence_minutes"] = diagnostic.get(
                "time_to_convergence_minutes"
            )

    # Populate fixed horizons plus MFE/MAE from the full 5-minute path.
    for signal in signals:
        entry_time = datetime.fromisoformat(signal["signal_time"])
        local_date = entry_time.astimezone(EASTERN).date()
        entry_prices = signal.get("entry_prices", {})
        if not all(value for value in entry_prices.values()):
            continue

        path_returns = []
        for timestamp, panel in zip(timestamps, panels):
            if timestamp < entry_time or timestamp > entry_time + timedelta(minutes=120):
                continue
            if timestamp.astimezone(EASTERN).date() != local_date:
                continue
            value = _portfolio_return(signal, entry_prices, panel)
            if value is not None:
                path_returns.append(value)
        if path_returns:
            signal.setdefault("path_stats", {})["mfe"] = max(path_returns)
            signal["path_stats"]["mae"] = min(path_returns)

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


def _group_summary(signals, key):
    result = {}
    for signal in signals:
        label = key(signal)
        if not label:
            continue
        group = result.setdefault(label, {"signals": 0, "returns_60m": [], "mfe": [], "mae": [], "convergence_minutes": []})
        group["signals"] += 1
        horizon = signal.get("horizons", {}).get("60m", {}).get("net_fixed_weight_return")
        if horizon is not None:
            group["returns_60m"].append(horizon)
        stats = signal.get("path_stats", {})
        if stats.get("mfe") is not None:
            group["mfe"].append(stats["mfe"])
        if stats.get("mae") is not None:
            group["mae"].append(stats["mae"])
        if stats.get("time_to_convergence_minutes") is not None:
            group["convergence_minutes"].append(stats["time_to_convergence_minutes"])
    return {
        label: {
            "signals": values["signals"],
            "average_60m_return": _mean(values["returns_60m"]),
            "positive_60m_rate": (
                sum(value > 0 for value in values["returns_60m"]) / len(values["returns_60m"])
                if values["returns_60m"] else None
            ),
            "average_mfe": _mean(values["mfe"]),
            "average_mae": _mean(values["mae"]),
            "average_time_to_convergence_minutes": _mean(values["convergence_minutes"]),
        }
        for label, values in sorted(result.items())
    }


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
            "average_return": _mean(values),
            "positive_rate": sum(value > 0 for value in values) / len(values) if values else None,
        }

    mfes = [s.get("path_stats", {}).get("mfe") for s in signals]
    maes = [s.get("path_stats", {}).get("mae") for s in signals]
    convergence_times = [s.get("path_stats", {}).get("time_to_convergence_minutes") for s in signals]
    mfes = [value for value in mfes if value is not None]
    maes = [value for value in maes if value is not None]
    convergence_times = [value for value in convergence_times if value is not None]

    return {
        "qualifying_candidates": len(signals),
        "selected_paper_entries": len(selected),
        "resolved_paper_entries": len(resolved),
        "converged_paper_entries": len(converged),
        "paper_entry_convergence_rate": len(converged) / len(resolved) if resolved else None,
        "average_mfe": _mean(mfes),
        "average_mae": _mean(maes),
        "average_time_to_convergence_minutes": _mean(convergence_times),
        "horizons": horizon_summary,
        "by_z_bucket": _group_summary(signals, lambda signal: signal.get("z_bucket")),
        "by_time_bucket": _group_summary(signals, lambda signal: signal.get("time_bucket")),
        "by_market_regime": _group_summary(
            signals, lambda signal: signal.get("market_context", {}).get("market_regime")
        ),
    }
