#!/usr/bin/env python3
"""Expose whether a scheduled research run is inside the US market window."""

from __future__ import annotations

import os
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def is_research_window(moment: datetime | None = None) -> bool:
    current = (moment or datetime.now(EASTERN)).astimezone(EASTERN)
    return current.weekday() < 5 and time(9, 30) <= current.time() <= time(15, 55)


def main() -> None:
    active = "true" if is_research_window() else "false"
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"active={active}\n")
    print(f"active={active}")


if __name__ == "__main__":
    main()

