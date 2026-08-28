#!/usr/bin/env python3
from __future__ import annotations

import os

from residual_alpha.discord import post_webhook


def main() -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")
    repository = os.environ.get("GITHUB_REPOSITORY", "Residual Alpha")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_url = f"{server}/{repository}/actions/runs/{run_id}" if run_id else ""
    post_webhook(
        webhook,
        f"**Residual Alpha — hourly run failed**\nRepository: `{repository}`\n{run_url}",
    )


if __name__ == "__main__":
    main()

