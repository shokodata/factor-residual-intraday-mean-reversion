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
