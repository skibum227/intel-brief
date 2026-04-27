"""
Manages a persistent store of dismissed (noise) item fingerprints.
Stored at ~/.config/intel-brief/dismissed.json (outside the repo).
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger("intel_brief")

DISMISSED_PATH = Path.home() / ".config" / "intel-brief" / "dismissed.json"


def _read_entries() -> list[dict]:
    """Read raw entries from dismissed.json. Returns empty list on any error."""
    if not DISMISSED_PATH.exists():
        return []
    try:
        data = json.loads(DISMISSED_PATH.read_text())
        if not isinstance(data, list):
            log.warning("dismissed.json is not a list; resetting")
            return []
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read dismissed.json: %s", exc)
        return []


def _write_entries(entries: list[dict]) -> None:
    """Atomically write entries to dismissed.json."""
    DISMISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, indent=2)
    fd, tmp = tempfile.mkstemp(dir=DISMISSED_PATH.parent, suffix=".tmp")
    try:
        os.write(fd, payload.encode())
        os.close(fd)
        os.replace(tmp, DISMISSED_PATH)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_dismissed(max_age_days: int = 14) -> list[str]:
    """Return fingerprint strings, pruning expired entries from disk."""
    entries = _read_entries()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    keep = []
    result = []
    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry["dismissed_at"])
            if ts >= cutoff:
                keep.append(entry)
                result.append(entry["fingerprint"])
        except (KeyError, ValueError, TypeError):
            continue
    # Prune expired entries from disk
    if len(keep) < len(entries):
        _write_entries(keep)
    return result


def add_dismissed(fingerprint: str) -> None:
    """Append a fingerprint with current UTC timestamp. Deduplicates."""
    entries = _read_entries()
    if any(e.get("fingerprint") == fingerprint for e in entries):
        log.debug("Fingerprint already dismissed: %s", fingerprint)
        return
    entries.append({
        "fingerprint": fingerprint,
        "dismissed_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_entries(entries)


def remove_dismissed(fingerprint: str) -> None:
    """Remove entry matching fingerprint."""
    entries = _read_entries()
    filtered = [e for e in entries if e.get("fingerprint") != fingerprint]
    if len(filtered) < len(entries):
        _write_entries(filtered)
