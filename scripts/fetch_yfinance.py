#!/usr/bin/env python3
from __future__ import annotations

import argparse

from residual_alpha.yahoo import download_bars


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an intraday panel from Yahoo Finance")
    parser.add_argument("--universe", default="config/universe.csv")
    parser.add_argument("--output", default="data/intraday.csv")
    parser.add_argument("--period", default="5d")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    bars, symbols = download_bars(
        args.universe, args.output, args.period, args.interval, args.batch_size
    )
    print(f"Wrote {bars} complete bars for {symbols} symbols to {args.output}")


if __name__ == "__main__":
    main()
