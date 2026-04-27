"""
Tracks the last-run timestamp so each run only fetches new data.
State is stored at ~/.config/intel-brief/state.json (outside the repo).
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger("intel_brief")

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
    """Record the current time as the last successful run (atomic write)."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "version": 1,
        "last_run": datetime.now(timezone.utc).isoformat(),
    })
    # Write to temp file then atomically replace to avoid corruption
    fd, tmp = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".tmp")
    try:
        os.write(fd, payload.encode())
        os.close(fd)
        os.replace(tmp, STATE_PATH)
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def clear_last_run():
    """Delete the saved state, causing the next run to use the fallback lookback window."""
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"  State cleared: {STATE_PATH}")
