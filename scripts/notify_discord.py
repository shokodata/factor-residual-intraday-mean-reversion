#!/usr/bin/env python3
from __future__ import annotations

import argparse

from residual_alpha.discord import notify_from_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Residual Alpha metrics to Discord")
    parser.add_argument("metrics", help="path to metrics.json")
    parser.add_argument("--candidates", help="path to candidates.json")
    args = parser.parse_args()
    notify_from_file(args.metrics, args.candidates)


if __name__ == "__main__":
    main()
