"""Command-line entry point."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .backtest import BacktestConfig, run_backtest
from .data import read_bars
from .synthetic import generate


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
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "generate-demo":
        generate(args.output, args.bars)
        print(f"Wrote {args.output}")
        return
    config = BacktestConfig(
        beta_window=args.beta_window,
        residual_window=args.residual_window,
        minimum_beta_observations=args.minimum_beta_observations,
        entry_z=args.entry_z,
        exit_z=args.exit_z,
        cost_bps=args.cost_bps,
    )
    result = run_backtest(read_bars(args.input), config)
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
    candidates = [
        {
            "symbol": symbol,
            "direction": "LONG" if weight > 0 else "SHORT",
            "target_weight": weight,
            "residual_zscore": latest_zscores.get(symbol, 0.0),
        }
        for symbol, weight in latest_weights.items()
        if abs(weight) > 1e-8
    ]
    candidates.sort(key=lambda item: abs(item["target_weight"]), reverse=True)
    with (output / "candidates.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "as_of": result.timestamps[-1].isoformat() if result.timestamps else None,
                "candidates": candidates,
            },
            handle,
            indent=2,
        )
    with (output / "latest_signals.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "direction", "target_weight", "residual_zscore"],
        )
        writer.writeheader()
        writer.writerows(candidates)
    print(json.dumps(result.metrics, indent=2))


if __name__ == "__main__":
    main()
