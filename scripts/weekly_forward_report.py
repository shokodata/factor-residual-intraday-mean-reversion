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


def minutes(value):
    return "N/A" if value is None else f"{value:.0f}m"


def _append_groups(lines, title, groups):
    if not groups:
        return
    lines += ["", f"**{title} — 60m forward**"]
    for label, stats in groups.items():
        lines.append(
            f"• {label}: avg {pct(stats['average_60m_return'])} | +rate {pct(stats['positive_60m_rate'])} | n={stats['signals']}"
        )


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
        f"**Selected / resolved:** {summary['selected_paper_entries']} / {summary['resolved_paper_entries']}",
        f"**Paper-entry convergence:** {pct(summary['paper_entry_convergence_rate'])}",
        f"**Avg MFE / MAE:** {pct(summary.get('average_mfe'))} / {pct(summary.get('average_mae'))}",
        f"**Avg first convergence:** {minutes(summary.get('average_time_to_convergence_minutes'))}",
        "",
        "**Fixed-horizon performance — all qualifying candidates**",
    ]
    for label in ("15m", "30m", "60m", "120m", "EOD"):
        stats = summary["horizons"][label]
        lines.append(
            f"• {label}: avg {pct(stats['average_return'])} | positive {pct(stats['positive_rate'])} | n={stats['observations']}"
        )

    _append_groups(lines, "Entry |Z|", summary.get("by_z_bucket", {}))
    _append_groups(lines, "Entry time ET", summary.get("by_time_bucket", {}))
    _append_groups(lines, "Market regime", summary.get("by_market_regime", {}))

    if resolved:
        reasons = Counter(s["trade_outcome"].get("exit_reason") or "UNKNOWN" for s in resolved)
        holding_minutes = [(s["trade_outcome"].get("holding_bars") or 0) * 5 for s in resolved]
        returns = [s["trade_outcome"].get("net_return") for s in resolved]
        returns = [r for r in returns if r is not None]
        lines += [
            "",
            "**Mechanical paper-entry outcomes**",
            f"• Avg hold: {mean(holding_minutes):.0f}m | avg net: {pct(mean(returns) if returns else None)}",
            "• Exits: " + ", ".join(f"{reason} {count}" for reason, count in sorted(reasons.items())),
        ]

    lines += [
        "",
        "_Research only. MFE/MAE and fixed horizons use recorded hedge weights and the strategy cost assumption; no entry/exit rule was changed._",
    ]
    message = "\n".join(lines)
    if len(message) > 1950:
        message = message[:1900] + "\n…report truncated; full ledger remains in GitHub."
    return message


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
