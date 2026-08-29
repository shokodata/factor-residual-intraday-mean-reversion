"""Send the weekly residual-alpha forward-validation summary to Discord."""
from __future__ import annotations

import json
import os
import urllib.request
from collections import Counter
from statistics import mean

from residual_alpha.forward_validation import _load, build_summary

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")


def pct(value):
    return "N/A" if value is None else f"{value:.2%}"


def build_message():
    ledger = _load()
    signals = ledger.get("signals", [])
    summary = build_summary(ledger)
    selected = [s for s in signals if s.get("selected_paper_entry")]
    resolved = [s for s in selected if (s.get("trade_outcome") or {}).get("resolved")]

    lines = [
        "📊 **RESIDUAL ALPHA — WEEKLY FORWARD VALIDATION**",
        "",
        f"**Qualifying candidates:** {summary['qualifying_candidates']}",
        f"**Selected paper entries:** {summary['selected_paper_entries']}",
        f"**Resolved paper entries:** {summary['resolved_paper_entries']}",
        f"**Paper-entry convergence rate:** {pct(summary['paper_entry_convergence_rate'])}",
        "",
        "**Fixed-horizon performance — all qualifying candidates**",
    ]
    for label in ("15m", "30m", "60m", "120m", "EOD"):
        stats = summary["horizons"][label]
        lines.append(
            f"• {label}: avg {pct(stats['average_return'])} | positive {pct(stats['positive_rate'])} | n={stats['observations']}"
        )

    if resolved:
        reasons = Counter(s["trade_outcome"].get("exit_reason") or "UNKNOWN" for s in resolved)
        holding_minutes = [
            (s["trade_outcome"].get("holding_bars") or 0) * 5 for s in resolved
        ]
        returns = [s["trade_outcome"].get("net_return") for s in resolved]
        returns = [r for r in returns if r is not None]
        lines += [
            "",
            "**Mechanical paper-entry outcomes**",
            f"• Avg holding time: {mean(holding_minutes):.0f} min",
            f"• Avg net return: {pct(mean(returns) if returns else None)}",
            "• Exit reasons: " + ", ".join(f"{reason} {count}" for reason, count in sorted(reasons.items())),
        ]

    lines += [
        "",
        "_Forward observations are research results, not live executions. Fixed-horizon returns use the recorded hedge weights and the strategy cost assumption._",
    ]
    return "\n".join(lines)


def send(message):
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    payload = json.dumps({"username": "Residual Alpha Validation", "content": message}).encode("utf-8")
    request = urllib.request.Request(
        WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {response.status}")


def main():
    message = build_message()
    print(message)
    send(message)


if __name__ == "__main__":
    main()
