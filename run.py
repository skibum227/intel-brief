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
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.config import load_config, get_limit, log
from src.connectors import confluence, github, gmail, google_cal, jira, news, slack
from src.dismissed import load_dismissed
from src.obsidian import (load_recent_summaries, load_user_notes, load_completed_items,
                           load_daily_completion_counts, load_recurring_unchecked_items,
                           extract_critical_team_signals, load_prev_brief_fingerprints,
                           write_brief, load_last_brief_for_html)
from src.state import get_last_run, save_last_run, clear_last_run
from src.summarizer import summarize


def main():
    parser = argparse.ArgumentParser(description="Intel Brief")
    parser.add_argument("--project-update", action="store_true", help="Append weekly Project Status Update section")
    parser.add_argument("--html", action="store_true", help="Also render a modern HTML dashboard and open it in the browser")
    parser.add_argument("--render-html", action="store_true", help="Re-render HTML from the most recent brief without fetching new data")
    parser.add_argument("--prep", action="store_true", help="Generate meeting prep notes for upcoming meetings")
    parser.add_argument("--reset-state", action="store_true", help="Clear the last-run timestamp and exit (next run uses fallback lookback window)")
    args = parser.parse_args()

    config = load_config()

    if args.reset_state:
        clear_last_run()
        print("  Next run will use the fallback lookback window from config.yaml.")
        return

    if args.render_html:
        from src.html_report import write_html_report
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

    if args.prep:
        from src.summarizer import generate_meeting_prep
        from src.obsidian import write_meeting_prep

        print("\nMeeting Prep\n")
        since = get_last_run(fallback_hours=config.get("lookback_hours", 24))

        # (display_name, dict_key, module)
        prep_connectors = [
            ("Slack",      "slack",      slack),
            ("Jira",       "jira",       jira),
            ("Confluence", "confluence", confluence),
            ("Calendar",   "google_cal", google_cal),
            ("Gmail",      "gmail",      gmail),
        ]

        print("  Fetching sources...")
        all_updates = {}
        with ThreadPoolExecutor(max_workers=len(prep_connectors)) as executor:
            futures = {
                executor.submit(module.fetch_updates, config, since): (display, key)
                for display, key, module in prep_connectors
            }
            for future in as_completed(futures):
                display, key = futures[future]
                try:
                    updates = future.result()
                    all_updates[key] = updates
                    print(f"    ✓ {display:<12} {len(updates):>3} items")
                except Exception as e:
                    log.warning(f"{display} failed: {e}")
                    all_updates[key] = []

        meetings = all_updates.get("google_cal", [])
        if not meetings:
            print("  No upcoming meetings found.")
            return

        print(f"  {len(meetings)} upcoming meetings found")
        print("  Generating meeting prep via Claude...")
        prep_text = generate_meeting_prep(meetings, all_updates, config)
        print("    ✓ Meeting prep generated")

        write_meeting_prep(prep_text, config)
        print("\nDone.\n")
        return

    print("\nIntel Brief\n")

    since = get_last_run(fallback_hours=config.get("lookback_hours", 24))
    now = datetime.now(timezone.utc)
    lookback_hours = (now - since).total_seconds() / 3600

    print(f"  Window: {since.strftime('%Y-%m-%d %H:%M UTC')} → now ({lookback_hours:.1f}h)\n")

    # ── Fetch from all sources ───────────────────────────────────────────
    # (display_name, dict_key, module)
    connectors = [
        ("Slack",      "slack",      slack),
        ("Jira",       "jira",       jira),
        ("Confluence", "confluence", confluence),
        ("Calendar",   "google_cal", google_cal),
        ("Gmail",      "gmail",      gmail),
        ("GitHub",     "github",     github),
        ("News",       "news",       news),
    ]

    all_updates = {}
    any_failed = False

    print("  Fetching sources...")
    with ThreadPoolExecutor(max_workers=len(connectors)) as executor:
        futures = {
            executor.submit(module.fetch_updates, config, since): (display, key)
            for display, key, module in connectors
        }
        for future in as_completed(futures):
            display, key = futures[future]
            try:
                updates = future.result()
                all_updates[key] = updates
                print(f"    ✓ {display:<12} {len(updates):>3} items")
            except Exception as e:
                log.warning(f"{display} failed: {e}")
                all_updates[key] = []
                any_failed = True

    total = sum(len(v) for v in all_updates.values())
    print(f"\n  Total: {total} updates")

    if total == 0:
        print("  Nothing new. No brief generated.")
        if not any_failed:
            save_last_run()
        return

    # ── Generate brief ───────────────────────────────────────────────────
    history_days = get_limit(config, "history_window_days")
    recurring_days = get_limit(config, "recurring_window_days")

    print("  Loading context...")
    prior_context = load_recent_summaries(config, days=history_days)
    user_notes = load_user_notes(config, days=history_days)
    completed_items = load_completed_items(config, days=history_days)
    recurring_items = load_recurring_unchecked_items(config, days=recurring_days)
    team_signals = extract_critical_team_signals(all_updates)
    prev_fingerprints = load_prev_brief_fingerprints(config)
    dismissed_items = load_dismissed()

    print("  Generating brief via Claude...")
    summary = summarize(
        all_updates, lookback_hours, config,
        prior_context=prior_context, user_notes=user_notes,
        completed_items=completed_items, recurring_items=recurring_items,
        team_signals=team_signals, dismissed_items=dismissed_items,
    )
    print("    ✓ Brief generated")

    # ── Project update (optional) ────────────────────────────────────────
    project_update = ""
    if args.project_update:
        from src.connectors import google_sheets
        from src.summarizer import generate_project_update

        print("  Fetching project data...")
        projects = google_sheets.fetch_projects(config)
        print(f"    ✓ {len(projects)} active projects")

        confluence_pages = confluence.fetch_team_project_updates(config)
        print(f"    ✓ {len(confluence_pages)} Confluence update pages")

        print("  Fetching 7-day signals...")
        since_weekly = datetime.now(timezone.utc) - timedelta(days=7)
        weekly_updates = {}
        with ThreadPoolExecutor(max_workers=len(connectors)) as executor:
            futures = {
                executor.submit(module.fetch_updates, config, since_weekly): (display, key)
                for display, key, module in connectors
            }
            for future in as_completed(futures):
                display, key = futures[future]
                try:
                    weekly_updates[key] = future.result()
                except Exception as e:
                    log.warning(f"{display} weekly fetch failed: {e}")
                    weekly_updates[key] = []

        prior_context_weekly = load_recent_summaries(config, days=7)
        print("  Generating project status update...")
        project_update = generate_project_update(
            projects, weekly_updates, prior_context_weekly,
            config, confluence_pages=confluence_pages,
        )
        print("    ✓ Project update generated")

    # ── Write & serve ────────────────────────────────────────────────────
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
