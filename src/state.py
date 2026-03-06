"""
Tracks the last-run timestamp so each run only fetches new data.
State is stored at ~/.config/intel-brief/state.json (outside the repo).
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

STATE_PATH = Path.home() / ".config" / "intel-brief" / "state.json"


def get_last_run(fallback_hours: int = 24) -> datetime:
    """Return the timestamp of the last successful run, or fallback_hours ago."""
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text())
            return datetime.fromisoformat(data["last_run"])
        except (KeyError, ValueError, json.JSONDecodeError):
            pass
    return datetime.now(timezone.utc) - timedelta(hours=fallback_hours)


def save_last_run():
    """Record the current time as the last successful run."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_run": datetime.now(timezone.utc).isoformat()})
    )


def clear_last_run():
    """Delete the saved state, causing the next run to use the fallback lookback window."""
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"  State cleared: {STATE_PATH}")
