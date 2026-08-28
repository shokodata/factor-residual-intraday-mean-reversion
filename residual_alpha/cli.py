"""Command-line entry point."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from .backtest import BacktestConfig, run_backtest
from .data import read_bars
from .synthetic import generate
from .single_strategy import SingleStrategyConfig, run_single_strategy


SECTOR_ETFS = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Technology": "XLK",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Consumer": "XLY",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Factor-residual intraday mean-reversion research engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("generate-demo", help="write a deterministic synthetic price panel")
    demo.add_argument("output")
    demo.add_argument("--bars", type=int, default=500)
    backtest = subparsers.add_parser("backtest", help="run a walk-forward backtest")
    backtest.add_argument("input")
    backtest.add_argument("--output", default="results")
    backtest.add_argument("--beta-window", type=int, default=60)
    backtest.add_argument("--residual-window", type=int, default=30)
    backtest.add_argument("--minimum-beta-observations", type=int, default=30)
    backtest.add_argument("--entry-z", type=float, default=1.5)
    backtest.add_argument("--exit-z", type=float, default=0.35)
    backtest.add_argument("--cost-bps", type=float, default=1.0)
    single = subparsers.add_parser(
        "single-backtest", help="run the locked single-name strategy with ETF hedges"
    )
    single.add_argument("input")
    single.add_argument("--output", default="single-results")
    single.add_argument("--entry-z", type=float, default=1.5)
    single.add_argument("--maximum-entry-z", type=float, default=5.0)
    single.add_argument("--exit-z", type=float, default=0.35)
    single.add_argument("--cost-bps", type=float, default=1.0)
    single.add_argument("--validation-summary")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "generate-demo":
        generate(args.output, args.bars)
        print(f"Wrote {args.output}")
        return
    if args.command == "single-backtest":
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        report = run_single_strategy(
            read_bars(args.input),
            SingleStrategyConfig(
                entry_z=args.entry_z,
                maximum_entry_z=args.maximum_entry_z,
                exit_z=args.exit_z,
                cost_bps=args.cost_bps,
            ),
        )
        if args.validation_summary:
            with Path(args.validation_summary).open(encoding="utf-8") as handle:
                report["validation"] = json.load(handle)
        with (output / "single_report.json").open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
        with (output / "metrics.json").open("w", encoding="utf-8") as handle:
            json.dump(report["metrics"], handle, indent=2)
        with (output / "trades.csv").open("w", newline="", encoding="utf-8") as handle:
            fieldnames = list(report["trades"][0]) if report["trades"] else [
                "symbol", "sector", "direction", "entry_time", "entry_z", "stock_weight",
                "spy_weight", "sector_etf", "sector_etf_weight", "exit_time", "exit_z",
                "exit_reason", "holding_bars", "net_return",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report["trades"])
        print(json.dumps(report["metrics"], indent=2))
        return
    config = BacktestConfig(
        beta_window=args.beta_window,
        residual_window=args.residual_window,
        minimum_beta_observations=args.minimum_beta_observations,
        entry_z=args.entry_z,
        exit_z=args.exit_z,
        cost_bps=args.cost_bps,
    )
    bars = read_bars(args.input)
    result = run_backtest(bars, config)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(result.metrics, handle, indent=2)
    with (output / "equity.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "return", "equity", "turnover"])
        writer.writerows(zip(result.timestamps, result.returns, result.equity, result.turnover))
    with (output / "weights.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "symbol", "weight"])
        for timestamp, weights in zip(result.timestamps, result.weights):
            writer.writerows((timestamp, symbol, weight) for symbol, weight in weights.items())
    latest_weights = result.weights[-1] if result.weights else {}
    latest_zscores = result.zscores[-1] if result.zscores else {}
    latest_active = result.active_signals[-1] if result.active_signals else {}
    latest_betas = result.betas[-1] if result.betas else {}
    sectors = {bar.symbol: bar.sector for bar in bars}
    candidates = [
        {
            "symbol": symbol,
            "direction": "LONG" if latest_zscores.get(symbol, 0.0) < 0 else "SHORT",
            "target_weight": weight,
            "residual_zscore": latest_zscores.get(symbol, 0.0),
            "sector": sectors.get(symbol, "Unknown"),
        }
        for symbol, weight in latest_weights.items()
        if latest_active.get(symbol, False)
        and abs(latest_zscores.get(symbol, 0.0)) >= config.entry_z
        and abs(weight) > 1e-8
        and ((weight > 0) == (latest_zscores.get(symbol, 0.0) < 0))
    ]
    candidates.sort(key=lambda item: abs(item["target_weight"]), reverse=True)
    featured_pool = [item for item in candidates if abs(item["residual_zscore"]) <= 5.0]
    featured = max(featured_pool, key=lambda item: abs(item["residual_zscore"]), default=None)
    if featured:
        symbol = featured["symbol"]
        coefficients = latest_betas.get(symbol, [0.0, 0.0, 0.0])
        stock_weight = featured["target_weight"]
        signal_time = result.timestamps[-1].astimezone(ZoneInfo("America/New_York"))
        inside_entry_window = (
            signal_time.weekday() < 5 and time(10, 0) <= signal_time.time() <= time(14, 30)
        )
        featured = {
            **featured,
            "status": "PAPER ENTRY WINDOW" if inside_entry_window else "WATCH ONLY — NO NEW ENTRY",
            "market_beta": coefficients[1] if len(coefficients) > 1 else 0.0,
            "sector_beta": coefficients[2] if len(coefficients) > 2 else 0.0,
            "market_hedge": {"symbol": "SPY", "target_weight": -stock_weight * coefficients[1]},
            "sector_hedge": {
                "symbol": SECTOR_ETFS.get(featured["sector"], "sector ETF"),
                "target_weight": -stock_weight * coefficients[2],
            },
            "exit_rules": {
                "convergence": "abs(residual z) <= 0.35",
                "maximum_holding_minutes": 120,
                "mandatory_exit": "15:50 America/New_York",
            },
            "required_manual_check": "Check current company news and earnings before any paper entry.",
        }
    with (output / "candidates.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "as_of": result.timestamps[-1].isoformat() if result.timestamps else None,
                "universe_size": len(latest_weights),
                "active_candidate_count": len(candidates),
                "featured_candidate": featured,
                "candidates": candidates,
            },
            handle,
            indent=2,
        )
    with (output / "latest_signals.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "direction", "target_weight", "residual_zscore", "sector"],
        )
        writer.writeheader()
        writer.writerows(candidates)
    print(json.dumps(result.metrics, indent=2))


if __name__ == "__main__":
    main()
