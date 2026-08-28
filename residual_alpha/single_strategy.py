"""Locked, one-position intraday residual-reversion simulation."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from .data import Bar, price_panels
from .linalg import solve


EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SingleStrategyConfig:
    beta_window: int = 60
    residual_window: int = 30
    minimum_beta_observations: int = 30
    entry_z: float = 1.5
    maximum_entry_z: float = 5.0
    exit_z: float = 0.35
    widening_stop_z: float = 1.5
    maximum_holding_bars: int = 24
    cost_bps: float = 1.0
    ridge: float = 1e-6
    entry_start: time = time(10, 0)
    entry_end: time = time(14, 30)
    mandatory_exit: time = time(15, 40)
    decision_minute: int = 40
    maximum_entries_per_day: int = 1


@dataclass
class Trade:
    symbol: str
    sector: str
    direction: str
    entry_time: datetime
    entry_z: float
    stock_weight: float
    spy_weight: float
    sector_etf: str
    sector_etf_weight: float
    exit_time: datetime | None = None
    exit_z: float | None = None
    exit_reason: str | None = None
    holding_bars: int = 0
    net_return: float = 0.0


class RollingRidge:
    def __init__(self, window: int, size: int, ridge: float) -> None:
        self.window = window
        self.size = size
        self.ridge = ridge
        self.rows: deque[tuple[list[float], float]] = deque()
        self.gram = [[0.0] * size for _ in range(size)]
        self.target = [0.0] * size

    def __len__(self) -> int:
        return len(self.rows)

    def add(self, features: list[float], response: float) -> None:
        if len(self.rows) == self.window:
            old_x, old_y = self.rows.popleft()
            self._accumulate(old_x, old_y, -1.0)
        self.rows.append((features[:], response))
        self._accumulate(features, response, 1.0)

    def _accumulate(self, features: list[float], response: float, sign: float) -> None:
        for i in range(self.size):
            self.target[i] += sign * features[i] * response
            for j in range(self.size):
                self.gram[i][j] += sign * features[i] * features[j]

    def coefficients(self) -> list[float]:
        matrix = [row[:] for row in self.gram]
        for index in range(self.size):
            matrix[index][index] += self.ridge
        return solve(matrix, self.target[:])


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    center = _mean(values)
    return math.sqrt(sum((value - center) ** 2 for value in values) / (len(values) - 1))


def _drawdown(returns: list[float]) -> float:
    equity = peak = 1.0
    result = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        result = min(result, equity / peak - 1.0)
    return result


def run_single_strategy(
    bars: list[Bar], config: SingleStrategyConfig = SingleStrategyConfig()
) -> dict[str, Any]:
    timestamps, all_symbols, sectors, prices = price_panels(bars)
    stocks = [symbol for symbol in all_symbols if not sectors[symbol].startswith("__")]
    market_symbols = [symbol for symbol in all_symbols if sectors[symbol] == "__MARKET__"]
    sector_factors = {
        marker.removeprefix("__SECTOR__:"): symbol
        for symbol, marker in sectors.items()
        if marker.startswith("__SECTOR__:")
    }
    if len(market_symbols) != 1:
        raise ValueError("single strategy requires exactly one __MARKET__ factor")
    market_symbol = market_symbols[0]
    missing_sectors = set(sectors[symbol] for symbol in stocks) - set(sector_factors)
    if missing_sectors:
        raise ValueError(f"missing sector factor ETFs: {sorted(missing_sectors)}")

    models = {
        symbol: RollingRidge(config.beta_window, 3, config.ridge) for symbol in stocks
    }
    histories = {
        symbol: deque(maxlen=config.residual_window) for symbol in stocks
    }
    position: Trade | None = None
    position_weights: dict[str, float] = {}
    trades: list[Trade] = []
    bar_returns: list[float] = []
    latest_candidates: list[dict[str, Any]] = []
    latest_zscores: dict[str, float] = {}
    latest_betas: dict[str, list[float]] = {}
    last_event: dict[str, Any] = {"action": "NO_ENTRY", "reason": "No completed signal"}
    entries_by_date: dict[object, int] = {}

    for index in range(1, len(timestamps)):
        timestamp = timestamps[index]
        returns = {
            symbol: prices[index][symbol] / prices[index - 1][symbol] - 1.0
            for symbol in all_symbols
        }
        pnl = sum(weight * returns[symbol] for symbol, weight in position_weights.items())
        if position:
            position.holding_bars += 1
            position.net_return += pnl

        market_return = returns[market_symbol]
        current_zscores: dict[str, float] = {}
        current_betas: dict[str, list[float]] = {}
        for symbol in stocks:
            sector_return = returns[sector_factors[sectors[symbol]]]
            features = [1.0, market_return, sector_return]
            model = models[symbol]
            if len(model) >= config.minimum_beta_observations:
                coefficients = model.coefficients()
                residual = returns[symbol] - sum(
                    coefficient * feature
                    for coefficient, feature in zip(coefficients, features)
                )
                history = list(histories[symbol])
                scale = _std(history)
                current_zscores[symbol] = (
                    (residual - _mean(history)) / scale if scale else 0.0
                )
                current_betas[symbol] = coefficients
                histories[symbol].append(residual)
            model.add(features, returns[symbol])

        event: dict[str, Any] | None = None
        closed_this_bar = False
        local_timestamp = timestamp.astimezone(EASTERN)
        decision_bar = local_timestamp.minute == config.decision_minute
        if position:
            zscore = current_zscores.get(position.symbol)
            reason = None
            local_time = local_timestamp.time()
            if decision_bar and zscore is not None and abs(zscore) <= config.exit_z:
                reason = "CONVERGED"
            elif decision_bar and position.holding_bars >= config.maximum_holding_bars:
                reason = "120_MINUTE_LIMIT"
            elif local_time >= config.mandatory_exit:
                reason = "END_OF_DAY"
            elif decision_bar and zscore is not None and abs(zscore) >= abs(position.entry_z) + config.widening_stop_z:
                reason = "DISLOCATION_WIDENED"
            if reason:
                exit_cost = sum(abs(weight) for weight in position_weights.values()) * config.cost_bps / 10_000
                pnl -= exit_cost
                position.net_return -= exit_cost
                position.exit_time = timestamp
                position.exit_z = zscore
                position.exit_reason = reason
                trades.append(position)
                event = {"action": "EXIT", "trade": asdict(position)}
                position = None
                position_weights = {}
                closed_this_bar = True

        candidates: list[dict[str, Any]] = []
        if (
            not position
            and not closed_this_bar
            and decision_bar
            and local_timestamp.weekday() < 5
            and config.entry_start <= local_timestamp.time() <= config.entry_end
            and entries_by_date.get(local_timestamp.date(), 0) < config.maximum_entries_per_day
        ):
            for symbol, zscore in current_zscores.items():
                if not config.entry_z <= abs(zscore) <= config.maximum_entry_z:
                    continue
                coefficients = current_betas[symbol]
                direction = -1.0 if zscore > 0 else 1.0
                beta_market, beta_sector = coefficients[1], coefficients[2]
                gross = 1.0 + abs(beta_market) + abs(beta_sector)
                candidates.append(
                    {
                        "symbol": symbol,
                        "sector": sectors[symbol],
                        "direction": "LONG" if direction > 0 else "SHORT",
                        "residual_zscore": zscore,
                        "stock_weight": direction / gross,
                        "spy_weight": -direction * beta_market / gross,
                        "sector_etf": sector_factors[sectors[symbol]],
                        "sector_etf_weight": -direction * beta_sector / gross,
                    }
                )
            candidates.sort(key=lambda item: abs(item["residual_zscore"]), reverse=True)
            if candidates:
                candidate = candidates[0]
                position = Trade(
                    symbol=candidate["symbol"],
                    sector=candidate["sector"],
                    direction=candidate["direction"],
                    entry_time=timestamp,
                    entry_z=candidate["residual_zscore"],
                    stock_weight=candidate["stock_weight"],
                    spy_weight=candidate["spy_weight"],
                    sector_etf=candidate["sector_etf"],
                    sector_etf_weight=candidate["sector_etf_weight"],
                )
                position_weights = {
                    position.symbol: position.stock_weight,
                    market_symbol: position.spy_weight,
                    position.sector_etf: position.sector_etf_weight,
                }
                entries_by_date[local_timestamp.date()] = (
                    entries_by_date.get(local_timestamp.date(), 0) + 1
                )
                entry_cost = sum(abs(weight) for weight in position_weights.values()) * config.cost_bps / 10_000
                pnl -= entry_cost
                position.net_return -= entry_cost
                event = {"action": "ENTRY", "trade": asdict(position)}

        if position and event is None:
            event = {
                "action": "HOLD",
                "trade": asdict(position),
                "current_z": current_zscores.get(position.symbol),
                "remaining_minutes": max(
                    0, (config.maximum_holding_bars - position.holding_bars) * 5
                ),
            }
        if event:
            last_event = event
        bar_returns.append(pnl)
        latest_candidates = candidates
        latest_zscores = current_zscores
        latest_betas = current_betas

    if position:
        current_state = {
            "action": "HOLD",
            "trade": asdict(position),
            "current_z": latest_zscores.get(position.symbol),
            "remaining_minutes": max(0, (config.maximum_holding_bars - position.holding_bars) * 5),
        }
    else:
        current_state = last_event

    trade_returns = [trade.net_return for trade in trades]
    wins = [value for value in trade_returns if value > 0]
    losses = [value for value in trade_returns if value < 0]
    equity = math.prod(1.0 + value for value in bar_returns)
    metrics = {
        "total_return": equity - 1.0,
        "max_drawdown": _drawdown(bar_returns),
        "completed_trades": len(trades),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "average_trade_return": _mean(trade_returns) if trade_returns else 0.0,
        "average_winner": _mean(wins) if wins else 0.0,
        "average_loser": _mean(losses) if losses else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else 0.0,
    }
    return {
        "as_of": timestamps[-1].isoformat(),
        "universe_size": len(stocks),
        "metrics": metrics,
        "current_state": current_state,
        "latest_candidate_count": len(latest_candidates),
        "latest_candidates": latest_candidates[:10],
        "trades": [asdict(trade) for trade in trades],
        "methodology_note": (
            "Uses actual SPY and sector-ETF returns, locked positions, transaction costs, "
            "and mechanical exits. Historical news and earnings exclusions are not available."
        ),
    }
