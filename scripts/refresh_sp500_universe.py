#!/usr/bin/env python3
"""Refresh the current S&P 500 symbols and GICS sectors from Wikipedia."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

FACTOR_ROWS = [
    ("SPY", "__MARKET__"),
    ("XLC", "__SECTOR__:Communication Services"),
    ("XLY", "__SECTOR__:Consumer Discretionary"),
    ("XLP", "__SECTOR__:Consumer Staples"),
    ("XLE", "__SECTOR__:Energy"),
    ("XLF", "__SECTOR__:Financials"),
    ("XLV", "__SECTOR__:Health Care"),
    ("XLI", "__SECTOR__:Industrials"),
    ("XLK", "__SECTOR__:Information Technology"),
    ("XLB", "__SECTOR__:Materials"),
    ("XLRE", "__SECTOR__:Real Estate"),
    ("XLU", "__SECTOR__:Utilities"),
]


def yahoo_symbol(symbol: str) -> str:
    """Translate S&P display symbols to Yahoo Finance notation."""
    return symbol.strip().upper().replace(".", "-")


def fetch_constituents() -> list[tuple[str, str]]:
    from io import StringIO

    import pandas as pd
    import requests

    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "residual-alpha-research/0.1"},
        timeout=30,
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text), attrs={"id": "constituents"})
    if not tables:
        raise RuntimeError("S&P 500 constituent table was not found")
    table = tables[0]
    required = {"Symbol", "GICS Sector"}
    if not required.issubset(table.columns):
        raise RuntimeError("S&P 500 table columns changed")
    constituents = [
        (yahoo_symbol(str(row["Symbol"])), str(row["GICS Sector"]).strip())
        for _, row in table.iterrows()
    ]
    if not 495 <= len(constituents) <= 510:
        raise RuntimeError(f"unexpected S&P 500 constituent count: {len(constituents)}")
    return constituents


def write_universe(path: str | Path, constituents: list[tuple[str, str]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "sector"])
        writer.writerows(constituents)
        writer.writerows(FACTOR_ROWS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the current S&P 500 universe")
    parser.add_argument("--output", default="data/sp500_universe.csv")
    args = parser.parse_args()
    constituents = fetch_constituents()
    write_universe(args.output, constituents)
    print(f"Wrote {len(constituents)} S&P 500 constituents to {args.output}")


if __name__ == "__main__":
    main()
