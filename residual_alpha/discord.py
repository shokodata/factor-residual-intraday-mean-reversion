"""Discord webhook reporting without third-party dependencies."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


def format_metrics(
    metrics: dict[str, float],
    repository: str = "",
    candidate_report: dict | None = None,
) -> str:
    labels = (
        ("total_return", "Total return", "%"),
        ("sharpe", "Sharpe", "number"),
        ("max_drawdown", "Max drawdown", "%"),
        ("annualized_volatility", "Annualized volatility", "%"),
        ("average_one_way_turnover", "Average one-way turnover", "%"),
    )
    lines = ["**Residual Alpha — hourly research report**"]
    if repository:
        lines.append(f"Repository: `{repository}`")
    for key, label, style in labels:
        if key not in metrics:
            continue
        value = metrics[key]
        rendered = f"{value:.2%}" if style == "%" else f"{value:.2f}"
        lines.append(f"{label}: **{rendered}**")
    if candidate_report:
        lines.append(f"Signal timestamp: `{candidate_report.get('as_of', 'unknown')}`")
        candidates = candidate_report.get("candidates", [])
        universe_size = candidate_report.get("universe_size")
        if universe_size is not None:
            lines.append(
                f"Universe evaluated: **{universe_size} stocks**; "
                f"active candidates: **{candidate_report.get('active_candidate_count', len(candidates))}**"
            )
        featured = candidate_report.get("featured_candidate")
        if featured:
            market_hedge = featured["market_hedge"]
            sector_hedge = featured["sector_hedge"]
            lines.extend(
                [
                    "\n**Featured single-name paper setup**",
                    f"Status: **{featured['status']}**",
                    f"Stock: **{featured['direction']} {featured['symbol']}** — residual z "
                    f"`{featured['residual_zscore']:+.2f}`, target `{featured['target_weight']:+.1%}`",
                    f"Estimated hedges: **{_side(market_hedge['target_weight'])} {market_hedge['symbol']}** "
                    f"`{abs(market_hedge['target_weight']):.1%}` and "
                    f"**{_side(sector_hedge['target_weight'])} {sector_hedge['symbol']}** "
                    f"`{abs(sector_hedge['target_weight']):.1%}`",
                    "Exit: residual `|z| ≤ 0.35`, after **120 minutes**, or by **3:50 p.m. ET**—whichever comes first.",
                    f"Safety check: **{featured['required_manual_check']}**",
                ]
            )
        longs = [item for item in candidates if item.get("direction") == "LONG"][:5]
        shorts = [item for item in candidates if item.get("direction") == "SHORT"][:5]
        lines.append("\n**Long residual candidates**")
        lines.extend(_candidate_line(item) for item in longs) if longs else lines.append("None")
        lines.append("\n**Short residual candidates**")
        lines.extend(_candidate_line(item) for item in shorts) if shorts else lines.append("None")
    lines.append("\nResearch signal only — not a prediction or trade recommendation.")
    return "\n".join(lines)


def _candidate_line(candidate: dict) -> str:
    return (
        f"• **{candidate['symbol']}** — residual z `{candidate['residual_zscore']:+.2f}`, "
        f"neutral target `{candidate['target_weight']:+.1%}`"
    )


def _side(weight: float) -> str:
    return "LONG" if weight >= 0 else "SHORT"


def format_single_report(report: dict, repository: str = "") -> str:
    metrics = report["metrics"]
    lines = ["**Residual Alpha — locked single-name paper strategy**"]
    if repository:
        lines.append(f"Repository: `{repository}`")
    lines.extend(
        [
            f"Signal timestamp: `{report['as_of']}`",
            f"Universe evaluated: **{report['universe_size']} stocks**",
            f"Backtest: **{metrics['completed_trades']} completed trades**, "
            f"win rate **{metrics['win_rate']:.1%}**, average trade **{metrics['average_trade_return']:.3%}**",
            f"Test return: **{metrics['total_return']:.2%}**; max drawdown: **{metrics['max_drawdown']:.2%}**; "
            f"profit factor: **{metrics['profit_factor']:.2f}**",
        ]
    )
    validation = report.get("validation")
    if validation:
        lines.extend(
            [
                f"\n**Validation gate: {validation['status']}**",
                f"Longer test: **{validation['total_return']:.2%}**, "
                f"{validation['completed_trades']} trades, profit factor "
                f"**{validation['profit_factor']:.2f}**, max drawdown "
                f"**{validation['max_drawdown']:.2%}**",
                validation["note"],
            ]
        )
    state = report.get("current_state", {})
    action = state.get("action", "NO_ENTRY")
    action_label = action if not validation or validation.get("status") == "PASSED" else f"OBSERVE ONLY (model: {action})"
    lines.append(f"\n**Current action: {action_label}**")
    trade = state.get("trade")
    if trade:
        lines.extend(
            [
                f"Stock: **{trade['direction']} {trade['symbol']}** `{abs(trade['stock_weight']):.1%}`; "
                f"entry z `{trade['entry_z']:+.2f}`",
                f"Hedges: **{_side(trade['spy_weight'])} SPY** `{abs(trade['spy_weight']):.1%}`; "
                f"**{_side(trade['sector_etf_weight'])} {trade['sector_etf']}** "
                f"`{abs(trade['sector_etf_weight']):.1%}`",
                f"Entry: `{trade['entry_time']}`; current z: `{state.get('current_z', trade.get('exit_z'))}`",
            ]
        )
        if action == "HOLD":
            lines.append(f"Time remaining: **{state.get('remaining_minutes', 0)} minutes**")
        if action == "EXIT":
            lines.append(
                f"Exit reason: **{trade.get('exit_reason')}**; trade return: "
                f"**{trade.get('net_return', 0.0):.3%}**"
            )
    else:
        lines.append("No qualifying position is open. Do not force a trade.")

    featured_symbol = trade.get("symbol") if trade else None
    watchlist = [
        candidate
        for candidate in report.get("latest_candidates", [])
        if candidate.get("symbol") != featured_symbol
    ][:5]
    lines.append("\n**Ranked watchlist — alternatives, not tracked trades**")
    if watchlist:
        lines.extend(_single_watchlist_line(candidate, rank) for rank, candidate in enumerate(watchlist, 1))
    else:
        lines.append("No additional candidates currently meet the entry threshold.")
    lines.extend(
        [
            "Exit checks: hourly convergence, 120 minutes, widening by 1.5 z, or close by 3:50 p.m. ET.",
            "Safety: check current company news and earnings before acting on an ENTRY alert.",
            "\nPaper research only — historical event exclusions are not included.",
        ]
    )
    return "\n".join(lines)


def _single_watchlist_line(candidate: dict, rank: int) -> str:
    return (
        f"{rank}. **{candidate['direction']} {candidate['symbol']}** — z "
        f"`{candidate['residual_zscore']:+.2f}`, stock `{abs(candidate['stock_weight']):.1%}`; "
        f"hedges `{_side(candidate['spy_weight'])} SPY {abs(candidate['spy_weight']):.1%}` + "
        f"`{_side(candidate['sector_etf_weight'])} {candidate['sector_etf']} "
        f"{abs(candidate['sector_etf_weight']):.1%}`"
    )


def notify_single_report(report_path: str | Path) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    with Path(report_path).open(encoding="utf-8") as handle:
        report = json.load(handle)
    post_webhook(
        webhook_url,
        format_single_report(report, os.environ.get("GITHUB_REPOSITORY", "")),
    )
    print("Discord single-strategy report delivered successfully")


def post_webhook(webhook_url: str, content: str) -> None:
    if not webhook_url.startswith("https://"):
        raise ValueError("Discord webhook URL must use HTTPS")
    body = json.dumps({"content": content[:2000]}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "residual-alpha/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {response.status}")


def notify_from_file(metrics_path: str | Path, candidates_path: str | Path | None = None) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    with Path(metrics_path).open(encoding="utf-8") as handle:
        metrics = json.load(handle)
    candidate_report = None
    if candidates_path:
        with Path(candidates_path).open(encoding="utf-8") as handle:
            candidate_report = json.load(handle)
    post_webhook(
        webhook_url,
        format_metrics(metrics, os.environ.get("GITHUB_REPOSITORY", ""), candidate_report),
    )
    print("Discord report delivered successfully")
