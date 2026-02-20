#!/usr/bin/env python3
"""
Intel Brief
-----------
Fetches updates from Slack, Jira, Confluence, Google Calendar, and Gmail,
then generates an AI-summarized brief and writes it to your Obsidian vault.

Usage:
    python run.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

from src.connectors import confluence, gmail, google_cal, jira, slack
from src.obsidian import write_brief
from src.state import get_last_run, save_last_run
from src.summarizer import summarize


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    print("Intel Brief\n")
    config = load_config()

    since = get_last_run(fallback_hours=config.get("lookback_hours", 24))
    now = datetime.now(timezone.utc)
    lookback_hours = (now - since).total_seconds() / 3600

    print(f"  Window: {since.strftime('%Y-%m-%d %H:%M UTC')} → now ({lookback_hours:.1f}h)\n")

    connectors = [
        ("slack", slack),
        ("jira", jira),
        ("confluence", confluence),
        ("google_cal", google_cal),
        ("gmail", gmail),
    ]

    all_updates = {}
    any_failed = False

    for name, connector in connectors:
        print(f"  [{name}]", end=" ", flush=True)
        try:
            updates = connector.fetch_updates(config, since)
            all_updates[name] = updates
            print(f"{len(updates)} items")
        except Exception as e:
            print(f"FAILED — {e}")
            all_updates[name] = []
            any_failed = True

    total = sum(len(v) for v in all_updates.values())
    print(f"\n  Total: {total} updates")

    if total == 0:
        print("\n  Nothing new. No brief generated.")
        if not any_failed:
            save_last_run()
        return

    print("  Generating brief via Claude...")
    summary = summarize(all_updates, lookback_hours)

    write_brief(summary, all_updates, config)

    if not any_failed:
        save_last_run()
    else:
        print("\n  Note: some connectors failed — last-run timestamp not updated.")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
