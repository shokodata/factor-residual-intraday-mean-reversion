from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from residual_alpha.backtest import BacktestConfig, run_backtest
from residual_alpha.data import read_bars
from residual_alpha.discord import format_metrics
from residual_alpha.linalg import neutralize
from residual_alpha.synthetic import generate
from residual_alpha.yahoo import read_universe
from scripts.check_market_window import is_research_window


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


class YahooAdapterTests(unittest.TestCase):
    def test_default_universe_is_diversified(self) -> None:
        universe = read_universe("config/universe.csv")
        self.assertEqual(len(universe), 30)
        self.assertGreaterEqual(len(set(universe.values())), 5)


class MarketWindowTests(unittest.TestCase):
    def test_weekday_session_is_active(self) -> None:
        eastern = ZoneInfo("America/New_York")
        self.assertTrue(is_research_window(datetime(2026, 8, 27, 10, 47, tzinfo=eastern)))
        self.assertFalse(is_research_window(datetime(2026, 8, 27, 16, 0, tzinfo=eastern)))

    def test_weekend_is_inactive(self) -> None:
        eastern = ZoneInfo("America/New_York")
        self.assertFalse(is_research_window(datetime(2026, 8, 29, 10, 47, tzinfo=eastern)))


if __name__ == "__main__":
    unittest.main()
