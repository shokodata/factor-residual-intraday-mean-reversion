"""Walk-forward factor-residual mean-reversion backtest."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime

from .data import Bar, price_panels
from .linalg import neutralize, ridge_coefficients


@dataclass(frozen=True)
class BacktestConfig:
    beta_window: int = 60
    residual_window: int = 30
    minimum_beta_observations: int = 30
    entry_z: float = 1.5
    exit_z: float = 0.35
    max_gross_exposure: float = 1.0
    cost_bps: float = 1.0
    ridge: float = 1e-6
    bars_per_year: int = 252 * 78
    flatten_daily: bool = True


@dataclass(frozen=True)
class BacktestResult:
    timestamps: list[datetime]
    returns: list[float]
    equity: list[float]
    turnover: list[float]
    weights: list[dict[str, float]]
    residuals: list[dict[str, float]]
    zscores: list[dict[str, float]]
    metrics: dict[str, float]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    center = _mean(values)
    return math.sqrt(sum((value - center) ** 2 for value in values) / (len(values) - 1))


def _metrics(returns: list[float], turnover: list[float], bars_per_year: int) -> dict[str, float]:
    if not returns:
        return {}
    average = _mean(returns)
    volatility = _sample_std(returns)
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    annual_return = (equity ** (bars_per_year / len(returns)) - 1.0) if equity > 0 else -1.0
    return {
        "total_return": equity - 1.0,
        "annualized_return": annual_return,
        "annualized_volatility": volatility * math.sqrt(bars_per_year),
        "sharpe": (average / volatility * math.sqrt(bars_per_year)) if volatility else 0.0,
        "max_drawdown": max_drawdown,
        "average_one_way_turnover": _mean(turnover) / 2.0,
        "positive_bar_fraction": sum(value > 0 for value in returns) / len(returns),
    }


def run_backtest(bars: list[Bar], config: BacktestConfig = BacktestConfig()) -> BacktestResult:
    if config.minimum_beta_observations > config.beta_window:
        raise ValueError("minimum_beta_observations cannot exceed beta_window")
    timestamps, symbols, sectors, prices = price_panels(bars)
    sector_names = sorted(set(sectors.values()))
    observations: dict[str, deque[tuple[list[float], float]]] = {
        symbol: deque(maxlen=config.beta_window) for symbol in symbols
    }
    residual_history: dict[str, deque[float]] = {
        symbol: deque(maxlen=config.residual_window) for symbol in symbols
    }
    active: dict[str, bool] = defaultdict(bool)
    prior_weights = {symbol: 0.0 for symbol in symbols}
    output_returns: list[float] = []
    output_turnover: list[float] = []
    output_weights: list[dict[str, float]] = []
    output_residuals: list[dict[str, float]] = []
    output_zscores: list[dict[str, float]] = []
    output_times: list[datetime] = []
    equity = [1.0]

    for index in range(1, len(timestamps)):
        timestamp = timestamps[index]
        simple_returns = {
            symbol: prices[index][symbol] / prices[index - 1][symbol] - 1.0
            for symbol in symbols
        }
        market_return = _mean(list(simple_returns.values()))
        sector_return = {
            sector: _mean([simple_returns[s] for s in symbols if sectors[s] == sector])
            for sector in sector_names
        }

        # Positions chosen after the previous bar earn the current bar return.
        gross_pnl = sum(prior_weights[s] * simple_returns[s] for s in symbols)
        current_residuals: dict[str, float] = {}
        current_zscores: dict[str, float] = {}
        betas: dict[str, list[float]] = {}
        raw: dict[str, float] = {}

        for symbol in symbols:
            features = [1.0, market_return, sector_return[sectors[symbol]]]
            if len(observations[symbol]) >= config.minimum_beta_observations:
                coefficients = ridge_coefficients(list(observations[symbol]), config.ridge)
                residual = simple_returns[symbol] - sum(
                    coefficient * feature for coefficient, feature in zip(coefficients, features)
                )
                betas[symbol] = coefficients
                current_residuals[symbol] = residual
                history = list(residual_history[symbol])
                scale = _sample_std(history)
                z_score = (residual - _mean(history)) / scale if scale else 0.0
                current_zscores[symbol] = z_score
                if active[symbol] and abs(z_score) <= config.exit_z:
                    active[symbol] = False
                elif not active[symbol] and abs(z_score) >= config.entry_z:
                    active[symbol] = True
                raw[symbol] = -z_score if active[symbol] else 0.0
                residual_history[symbol].append(residual)
            else:
                raw[symbol] = 0.0
            observations[symbol].append((features, simple_returns[symbol]))

        tradable = [symbol for symbol in symbols if symbol in betas]
        new_weights = {symbol: 0.0 for symbol in symbols}
        if len(tradable) >= len(sector_names) + 2 and any(raw[symbol] for symbol in tradable):
            raw_vector = [raw[symbol] for symbol in tradable]
            exposures = [[1.0 for _ in tradable]]
            exposures.append([betas[symbol][1] for symbol in tradable])
            for sector in sector_names[:-1]:
                exposures.append([
                    betas[symbol][2] if sectors[symbol] == sector else 0.0
                    for symbol in tradable
                ])
            projected = neutralize(raw_vector, exposures, config.ridge)
            gross = sum(abs(weight) for weight in projected)
            if gross > 1e-12:
                scale = config.max_gross_exposure / gross
                for symbol, weight in zip(tradable, projected):
                    new_weights[symbol] = weight * scale

        if config.flatten_daily and index + 1 < len(timestamps):
            if timestamps[index + 1].date() != timestamp.date():
                new_weights = {symbol: 0.0 for symbol in symbols}
                active.clear()

        turnover = sum(abs(new_weights[s] - prior_weights[s]) for s in symbols)
        cost = turnover * config.cost_bps / 10_000.0
        net_return = gross_pnl - cost
        output_times.append(timestamp)
        output_returns.append(net_return)
        output_turnover.append(turnover)
        output_weights.append(new_weights.copy())
        output_residuals.append(current_residuals)
        output_zscores.append(current_zscores)
        equity.append(equity[-1] * (1.0 + net_return))
        prior_weights = new_weights

    return BacktestResult(
        timestamps=output_times,
        returns=output_returns,
        equity=equity[1:],
        turnover=output_turnover,
        weights=output_weights,
        residuals=output_residuals,
        zscores=output_zscores,
        metrics=_metrics(output_returns, output_turnover, config.bars_per_year),
    )
