#!/usr/bin/env python3
from __future__ import annotations

import argparse

from residual_alpha.discord import notify_from_file, notify_single_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Residual Alpha metrics to Discord")
    parser.add_argument("metrics", help="path to metrics.json")
    parser.add_argument("--candidates", help="path to candidates.json")
    parser.add_argument("--single-report", action="store_true")
    args = parser.parse_args()
    if args.single_report:
        notify_single_report(args.metrics)
    else:
        notify_from_file(args.metrics, args.candidates)


if __name__ == "__main__":
    main()
