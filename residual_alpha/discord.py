"""Discord webhook reporting without third-party dependencies."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


def format_metrics(metrics: dict[str, float], repository: str = "") -> str:
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
    lines.append("Research output only — not a live-trading instruction.")
    return "\n".join(lines)


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


def notify_from_file(metrics_path: str | Path) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    with Path(metrics_path).open(encoding="utf-8") as handle:
        metrics = json.load(handle)
    post_webhook(webhook_url, format_metrics(metrics, os.environ.get("GITHUB_REPOSITORY", "")))

