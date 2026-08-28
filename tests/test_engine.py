from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from residual_alpha.backtest import BacktestConfig, run_backtest
from residual_alpha.data import Bar, read_bars
from residual_alpha.discord import format_metrics, format_single_report
from residual_alpha.linalg import neutralize
from residual_alpha.synthetic import generate
from residual_alpha.yahoo import read_universe
from residual_alpha.single_strategy import SingleStrategyConfig, run_single_strategy
from scripts.check_market_window import is_research_window
from scripts.refresh_sp500_universe import yahoo_symbol


class LinearAlgebraTests(unittest.TestCase):
    def test_projection_removes_exposures(self) -> None:
        raw = [1.0, -0.2, 0.5, -0.7]
        exposures = [[1.0] * 4, [0.8, 1.2, 0.7, 1.1]]
        result = neutralize(raw, exposures)
        for exposure in exposures:
            self.assertAlmostEqual(sum(x * w for x, w in zip(exposure, result)), 0.0, places=6)


class BacktestTests(unittest.TestCase):
    def test_end_to_end_and_neutrality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.csv"
            generate(path, bars=240)
            result = run_backtest(
                read_bars(path),
                BacktestConfig(beta_window=30, residual_window=15, minimum_beta_observations=20),
            )
        self.assertEqual(len(result.timestamps), 239)
        self.assertTrue(result.metrics)
        self.assertTrue(any(sum(abs(v) for v in weights.values()) > 0 for weights in result.weights))
        for weights in result.weights:
            self.assertLessEqual(sum(abs(value) for value in weights.values()), 1.000001)
            self.assertAlmostEqual(sum(weights.values()), 0.0, places=5)


class DiscordTests(unittest.TestCase):
    def test_metric_report_format(self) -> None:
        report = format_metrics(
            {"total_return": 0.0123, "sharpe": 1.25, "max_drawdown": -0.02},
            "owner/repository",
        )
        self.assertIn("1.23%", report)
        self.assertIn("1.25", report)
        self.assertIn("owner/repository", report)

    def test_report_includes_ranked_candidates(self) -> None:
        report = format_metrics(
            {"total_return": 0.01},
            candidate_report={
                "as_of": "2026-08-27T15:55:00-04:00",
                "universe_size": 500,
                "active_candidate_count": 2,
                "featured_candidate": {
                    "symbol": "AAA",
                    "direction": "LONG",
                    "target_weight": 0.08,
                    "residual_zscore": -2.1,
                    "status": "PAPER ENTRY WINDOW",
                    "market_hedge": {"symbol": "SPY", "target_weight": -0.05},
                    "sector_hedge": {"symbol": "XLK", "target_weight": -0.03},
                    "required_manual_check": "Check current company news and earnings before any paper entry.",
                },
                "candidates": [
                    {"symbol": "AAA", "direction": "LONG", "target_weight": 0.08, "residual_zscore": -2.1},
                    {"symbol": "BBB", "direction": "SHORT", "target_weight": -0.07, "residual_zscore": 1.9},
                ],
            },
        )
        self.assertIn("Long residual candidates", report)
        self.assertIn("**AAA**", report)
        self.assertIn("**BBB**", report)
        self.assertIn("-2.10", report)
        self.assertIn("500 stocks", report)
        self.assertIn("Featured single-name paper setup", report)
        self.assertIn("SHORT SPY", report)
        self.assertIn("120 minutes", report)

    def test_single_strategy_report_is_actionable(self) -> None:
        report = format_single_report(
            {
                "as_of": "2026-08-28T13:15:00-04:00",
                "universe_size": 500,
                "metrics": {
                    "completed_trades": 4,
                    "win_rate": 0.5,
                    "average_trade_return": 0.001,
                    "total_return": 0.004,
                    "max_drawdown": -0.002,
                    "profit_factor": 1.2,
                },
                "current_state": {
                    "action": "HOLD",
                    "current_z": 1.1,
                    "remaining_minutes": 55,
                    "trade": {
                        "symbol": "AAA", "direction": "SHORT", "stock_weight": -0.6,
                        "entry_z": 2.2, "spy_weight": -0.1, "sector_etf": "XLK",
                        "sector_etf_weight": 0.3, "entry_time": "2026-08-28T12:10:00-04:00",
                    },
                },
                "latest_candidates": [
                    {
                        "symbol": "AAA", "direction": "SHORT", "residual_zscore": 2.2,
                        "stock_weight": -0.6, "spy_weight": -0.1,
                        "sector_etf": "XLK", "sector_etf_weight": 0.3,
                    },
                    {
                        "symbol": "BBB", "direction": "LONG", "residual_zscore": -1.9,
                        "stock_weight": 0.55, "spy_weight": -0.25,
                        "sector_etf": "XLK", "sector_etf_weight": -0.2,
                    },
                ],
            }
        )
        self.assertIn("Current action: HOLD", report)
        self.assertIn("55 minutes", report)
        self.assertIn("SHORT AAA", report)
        self.assertIn("Ranked watchlist", report)
        self.assertIn("LONG BBB", report)
        self.assertNotIn("1. **SHORT AAA**", report)


class YahooAdapterTests(unittest.TestCase):
    def test_default_universe_is_diversified(self) -> None:
        universe = read_universe("config/universe.csv")
        self.assertEqual(len(universe), 30)
        self.assertGreaterEqual(len(set(universe.values())), 5)

    def test_sp500_symbol_conversion(self) -> None:
        self.assertEqual(yahoo_symbol("BRK.B"), "BRK-B")
        self.assertEqual(yahoo_symbol("bf.b"), "BF-B")


class MarketWindowTests(unittest.TestCase):
    def test_weekday_session_is_active(self) -> None:
        eastern = ZoneInfo("America/New_York")
        self.assertTrue(is_research_window(datetime(2026, 8, 27, 10, 47, tzinfo=eastern)))
        self.assertFalse(is_research_window(datetime(2026, 8, 27, 16, 0, tzinfo=eastern)))

    def test_weekend_is_inactive(self) -> None:
        eastern = ZoneInfo("America/New_York")
        self.assertFalse(is_research_window(datetime(2026, 8, 29, 10, 47, tzinfo=eastern)))


class SingleStrategyTests(unittest.TestCase):
    def test_positions_are_hedged_and_time_limited(self) -> None:
        import math
        import random

        random.seed(11)
        eastern = ZoneInfo("America/New_York")
        start = datetime(2026, 8, 24, 9, 30, tzinfo=eastern)
        sectors = {"AAA": "Technology", "BBB": "Technology", "CCC": "Technology",
                   "DDD": "Financials", "EEE": "Financials", "FFF": "Financials",
                   "SPY": "__MARKET__", "XLK": "__SECTOR__:Technology",
                   "XLF": "__SECTOR__:Financials"}
        prices = {symbol: 100.0 for symbol in sectors}
        states = {symbol: 0.0 for symbol in "AAA BBB CCC DDD EEE FFF".split()}
        bars = []
        timestamp = start
        produced = 0
        while produced < 240:
            if timestamp.weekday() >= 5 or timestamp.time() > datetime.strptime("15:55", "%H:%M").time():
                timestamp = (timestamp + timedelta(days=1)).replace(hour=9, minute=30)
                continue
            market = random.gauss(0, 0.0005)
            tech = market + random.gauss(0, 0.0003)
            financials = market + random.gauss(0, 0.0003)
            moves = {"SPY": market, "XLK": tech, "XLF": financials}
            for symbol in states:
                states[symbol] = -0.6 * states[symbol] + random.gauss(0, 0.0015)
                factor = tech if sectors[symbol] == "Technology" else financials
                moves[symbol] = 0.3 * market + 0.8 * factor + states[symbol]
            for symbol, sector in sectors.items():
                prices[symbol] *= math.exp(moves[symbol])
                bars.append(Bar(timestamp, symbol, prices[symbol], sector))
            timestamp += timedelta(minutes=5)
            produced += 1
        report = run_single_strategy(
            bars,
            SingleStrategyConfig(
                beta_window=20, residual_window=10, minimum_beta_observations=12,
                entry_z=1.2, maximum_entry_z=5.0, maximum_holding_bars=12,
            ),
        )
        self.assertGreater(report["metrics"]["completed_trades"], 0)
        for trade in report["trades"]:
            gross = abs(trade["stock_weight"]) + abs(trade["spy_weight"]) + abs(trade["sector_etf_weight"])
            self.assertAlmostEqual(gross, 1.0, places=6)
            self.assertLessEqual(trade["holding_bars"], 12)


if __name__ == "__main__":
    unittest.main()
