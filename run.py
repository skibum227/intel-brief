#!/usr/bin/env python3
"""
Intel Brief
-----------
Fetches updates from Slack, Jira, Confluence, Google Calendar, and Gmail,
then generates an AI-summarized brief and writes it to your Obsidian vault.

Usage:
    python run.py
    python run.py --project-update   # adds weekly Project Status Update section
    python run.py --html             # also renders a modern HTML dashboard (opens in browser)
    python run.py --html --project-update
    python run.py --render-html      # re-render HTML from the last brief without fetching new data
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

from src.connectors import confluence, github, gmail, google_cal, jira, slack
from src.obsidian import (load_recent_summaries, load_user_notes, load_completed_items,
                           load_daily_completion_counts, load_recurring_unchecked_items,
                           extract_critical_team_signals, load_prev_brief_fingerprints,
                           write_brief, load_last_brief_for_html)
from src.state import get_last_run, save_last_run, clear_last_run
from src.summarizer import summarize


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Intel Brief")
    parser.add_argument("--project-update", action="store_true", help="Append weekly Project Status Update section")
    parser.add_argument("--html", action="store_true", help="Also render a modern HTML dashboard and open it in the browser")
    parser.add_argument("--render-html", action="store_true", help="Re-render HTML from the most recent brief without fetching new data")
    parser.add_argument("--reset-state", action="store_true", help="Clear the last-run timestamp and exit (next run uses fallback lookback window)")
    args = parser.parse_args()

    if args.reset_state:
        clear_last_run()
        print("  Next run will use the fallback lookback window from config.yaml.")
        return

    if args.render_html:
        from src.html_report import write_html_report
        config = load_config()
        brief = load_last_brief_for_html(config)
        if brief is None:
            print("  No recent brief found to render.")
            return
        print(f"  Re-rendering HTML from brief dated {brief['generated_at'].strftime('%Y-%m-%d %H:%M')} ...")
        all_updates = {s: [] for s in brief["sources"]}
        prev_fingerprints = load_prev_brief_fingerprints(config)
        _, httpd = write_html_report(
            brief["summary"], all_updates, config,
            lookback_hours=None, now=brief["generated_at"],
            project_update=brief["project_update"],
            md_path=brief.get("md_path"),
            prev_fingerprints=prev_fingerprints,
        )
        print(f"  Sync server: http://127.0.0.1:{httpd.server_address[1]}/ — checkboxes sync to Obsidian")
        print("  Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Sync server stopped.")
        return

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
        ("github", github),
    ]

    all_updates = {}
    any_failed = False

    print("  Fetching from all sources in parallel...")
    with ThreadPoolExecutor(max_workers=len(connectors)) as executor:
        futures = {
            executor.submit(connector.fetch_updates, config, since): name
            for name, connector in connectors
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                updates = future.result()
                all_updates[name] = updates
                print(f"  [{name}] {len(updates)} items")
            except Exception as e:
                print(f"  [{name}] FAILED — {e}")
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
    prior_context = load_recent_summaries(config, days=3)
    user_notes = load_user_notes(config, days=3)
    completed_items = load_completed_items(config, days=3)
    recurring_items = load_recurring_unchecked_items(config, days=5)
    team_signals = extract_critical_team_signals(all_updates)
    prev_fingerprints = load_prev_brief_fingerprints(config)
    summary = summarize(all_updates, lookback_hours, prior_context=prior_context, user_notes=user_notes, completed_items=completed_items, recurring_items=recurring_items, team_signals=team_signals)

    project_update = ""
    if args.project_update:
        from src.connectors import google_sheets
        from src.summarizer import generate_project_update

        print("  Fetching projects from Google Sheet...")
        projects = google_sheets.fetch_projects(config)
        print(f"  {len(projects)} active projects found")

        print("  Fetching team project update pages from Confluence...")
        confluence_pages = confluence.fetch_team_project_updates(config)
        print(f"  {len(confluence_pages)} Confluence project update pages fetched")

        print("  Fetching 7-day signals for project update...")
        since_weekly = datetime.now(timezone.utc) - timedelta(days=7)
        weekly_updates = {}
        with ThreadPoolExecutor(max_workers=len(connectors)) as executor:
            futures = {
                executor.submit(connector.fetch_updates, config, since_weekly): name
                for name, connector in connectors
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    weekly_updates[name] = future.result()
                except Exception as e:
                    print(f"  [{name}] weekly fetch failed — {e}")
                    weekly_updates[name] = []

        prior_context_weekly = load_recent_summaries(config, days=7)
        print("  Generating project status update...")
        project_update = generate_project_update(
            projects, weekly_updates, prior_context_weekly, confluence_pages=confluence_pages
        )

    md_path = write_brief(summary, all_updates, config, project_update=project_update)

    httpd = None
    if args.html:
        from src.html_report import write_html_report
        _, httpd = write_html_report(
            summary, all_updates, config, lookback_hours, now,
            project_update=project_update, md_path=md_path,
            prev_fingerprints=prev_fingerprints,
        )

    if not any_failed:
        save_last_run()
    else:
        print("\n  Note: some connectors failed — last-run timestamp not updated.")

    if httpd:
        port = httpd.server_address[1]
        print(f"\n  Sync server: http://127.0.0.1:{port}/ — checkboxes sync to Obsidian")
        print("  Press Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Sync server stopped.")
    else:
        print("\nDone.\n")


if __name__ == "__main__":
    main()
