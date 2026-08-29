"""Update the persistent residual-alpha forward-validation ledger."""

from __future__ import annotations

import argparse
import json

from residual_alpha.forward_validation import update_forward_validation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("bars")
    parser.add_argument("--ledger", default="forward_validation.json")
    args = parser.parse_args()
    summary = update_forward_validation(args.report, args.bars, args.ledger)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
