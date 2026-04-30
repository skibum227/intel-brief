import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from src.config import get_vault_path, get_output_dir

_NOTES_PLACEHOLDER = "<!-- Add your notes here. They will be read into tomorrow's brief. -->"
_TODOS_PLACEHOLDER = "<!-- Add tasks here. Unchecked items carry forward to the next brief. -->"

_CHECKBOX_SECTIONS = {"Project Pulse", "Priorities & Action Items", "Who Needs a Response"}


def _fingerprint(text: str, word_count: int = 7) -> str:
    """Normalize a checklist item to a comparable fingerprint."""
    text = re.sub(r'[*_`\[\]]', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[^\x00-\x7F]', '', text)
    text = re.sub(r'[^\w\s]', ' ', text).lower()
    return ' '.join(text.split()[:word_count])


def _iter_recent_briefs(config: dict, days: int):
    """Yield (date_str, path, text) for brief files within the last `days` days."""
    output_dir = get_output_dir(config)
    if not output_dir.exists():
        return

    cutoff_date = (datetime.now() - timedelta(days=days)).date()
    results = []

    # New format: YYYYMM/DD HH-MM.md
    for path in output_dir.glob("*/*.md"):
        try:
            dt = datetime.strptime(f"{path.parent.name}/{path.stem}", "%Y%m/%d %H-%M")
        except ValueError:
            continue
        if dt.date() >= cutoff_date:
            results.append((dt, path))

    # Legacy format: YYYY-MM-DD.md
    for path in output_dir.glob("????-??-??.md"):
        try:
            dt = datetime.strptime(path.stem, "%Y-%m-%d")
        except ValueError:
            continue
        if dt.date() >= cutoff_date:
            results.append((dt, path))

    results.sort(key=lambda x: x[0], reverse=True)
    for dt, path in results:
        yield dt.strftime("%Y-%m-%d %H:%M"), path, path.read_text(encoding="utf-8")


def load_recent_summaries(config: dict, days: int = 3) -> str:
    """Return the LLM-generated summary sections from the last `days` brief files."""
    sections = []
    for date_str, _path, text in _iter_recent_briefs(config, days):
        # Strip frontmatter
        parts = text.split("---", 2)
        body = parts[2] if len(parts) >= 3 else text
        # Strip raw data block
        raw_marker = "\n---\n\n## Raw Data"
        if raw_marker in body:
            body = body.split(raw_marker)[0]
        # Strip the My Notes section — loaded separately via load_user_notes
        notes_marker = "\n---\n\n## My Notes"
        if notes_marker in body:
            body = body.split(notes_marker)[0]
        sections.append(f"### {date_str}\n{body.strip()}")

    return "\n\n".join(sections)


def load_user_notes(config: dict, days: int = 3) -> str:
    """Return user-written notes from the last `days` brief files."""
    sections = []
    for date_str, _path, text in _iter_recent_briefs(config, days):
        notes_marker = "\n---\n\n## My Notes"
        if notes_marker not in text:
            continue
        notes_text = text.split(notes_marker, 1)[1].strip()
        # Skip empty or placeholder-only sections
        cleaned = notes_text.replace(_NOTES_PLACEHOLDER, "").strip()
        if not cleaned:
            continue
        sections.append(f"### {date_str}\n{cleaned}")

    return "\n\n".join(sections)


def load_open_todos(config: dict) -> list[str]:
    """Return unchecked todo items from the most recent brief's My ToDos section."""
    for _date_str, _path, text in _iter_recent_briefs(config, days=7):
        todos_marker = "\n## My ToDos\n"
        if todos_marker not in text:
            continue
        todos_text = text.split(todos_marker, 1)[1]
        # Stop at next section boundary
        for boundary in ("\n---\n", "\n## "):
            if boundary in todos_text:
                todos_text = todos_text.split(boundary, 1)[0]
        items = []
        for line in todos_text.splitlines():
            if line.startswith("- [ ]"):
                items.append(line[5:].strip())
        return items  # Only check the most recent brief
    return []


def load_daily_completion_counts(config: dict, days: int = 7) -> list[int]:
    """Return list of checked-task counts per day for the last `days` days (oldest first)."""
    from collections import defaultdict
    from datetime import date, timedelta

    counts: dict[str, int] = defaultdict(int)
    for date_str, _path, text in _iter_recent_briefs(config, days):
        day = date_str[:10]  # YYYY-MM-DD
        for line in text.splitlines():
            if line.startswith("- [x]"):
                counts[day] += 1

    today = date.today()
    return [counts.get((today - timedelta(days=days - 1 - i)).isoformat(), 0) for i in range(days)]


def load_recurring_unchecked_items(config: dict, days: int = 5, min_appearances: int = 2) -> str:
    """Find unchecked action items that appear unresolved across multiple recent briefs."""
    from collections import defaultdict

    day_items: dict[str, list] = {}
    for date_str, _path, text in _iter_recent_briefs(config, days):
        items = []
        in_section = False
        for line in text.splitlines():
            if line.startswith('## '):
                in_section = line[3:].strip() in _CHECKBOX_SECTIONS
            elif in_section and line.startswith('- [ ]'):
                raw = line[5:].strip()
                fp = _fingerprint(raw)
                if len(fp) > 8:
                    items.append((fp, raw))
        day_items[date_str] = items

    fp_appearances: dict[str, list] = defaultdict(list)
    for date_str, items in day_items.items():
        seen: set[str] = set()
        for fp, original in items:
            if fp not in seen:
                fp_appearances[fp].append((date_str, original))
                seen.add(fp)

    recurring = []
    for fp, appearances in fp_appearances.items():
        if len(appearances) >= min_appearances:
            most_recent_text = sorted(appearances, reverse=True)[0][1]
            recurring.append((len(appearances), most_recent_text))

    if not recurring:
        return ""

    recurring.sort(reverse=True)
    lines = [f"- {text} ({count} days unresolved)" for count, text in recurring[:8]]
    return "\n".join(lines)


def extract_critical_team_signals(all_updates: dict) -> str:
    """Return ONLY critical team health signals: explicitly blocked tickets and
    people with 3+ high-priority tickets that have received zero comments."""
    from collections import defaultdict

    signals = []

    # --- Explicitly blocked Jira tickets ---
    blocked = []
    stale_by_person: dict[str, list] = defaultdict(list)

    for ticket in all_updates.get("jira", []):
        status = ticket.get("status", "").lower()
        assignee = ticket.get("assignee", "Unassigned")
        priority = ticket.get("priority", "").lower()
        labels = [l.lower() for l in ticket.get("labels", [])]

        if "blocked" in status or any("block" in l or "impediment" in l for l in labels):
            blocked.append(
                f"  - **{ticket.get('key','')}** ({assignee}): {ticket.get('summary','')[:70]}"
            )

        if priority in ("highest", "high", "critical") and assignee not in ("Unassigned", ""):
            if not ticket.get("recent_comments"):
                stale_by_person[assignee].append(ticket.get("key", ""))

    if blocked:
        signals.append(f"BLOCKED TICKETS ({len(blocked)}):\n" + "\n".join(blocked[:6]))

    critical_stale = {p: keys for p, keys in stale_by_person.items() if len(keys) >= 3}
    if critical_stale:
        lines = [f"  - **{p}**: {', '.join(keys[:5])}" for p, keys in critical_stale.items()]
        signals.append(
            "STALE HIGH-PRIORITY TICKETS (assigned, no recent comments):\n" + "\n".join(lines)
        )

    return "\n\n".join(signals)


def load_prev_brief_fingerprints(config: dict) -> list[str]:
    """Return normalized fingerprints of the previous brief's action items for diff highlighting."""
    results = list(_iter_recent_briefs(config, days=2))
    if len(results) < 2:
        return []

    # results are sorted newest first; second entry is yesterday's brief
    _, _, text = results[1]
    fps = []
    in_section = False
    for line in text.splitlines():
        if line.startswith('## '):
            in_section = line[3:].strip() in _CHECKBOX_SECTIONS
        elif in_section and (line.startswith('- [ ]') or line.startswith('- [x]')):
            raw = line[5:].strip()
            fp = _fingerprint(raw, word_count=6)
            if len(fp) > 5:
                fps.append(fp)
    return fps


def load_completed_items(config: dict, days: int = 3) -> str:
    """Return checked-off items from the three checkbox sections of recent briefs."""
    completed = []
    for date_str, _path, text in _iter_recent_briefs(config, days):
        current_section = None
        for line in text.splitlines():
            if line.startswith("## "):
                section_name = line[3:].strip()
                current_section = section_name if section_name in _CHECKBOX_SECTIONS else None
            elif current_section and line.startswith("- [x]"):
                item_text = line[len("- [x]"):].strip()
                completed.append(f"- {item_text} ({date_str})")

    return "\n".join(completed)


def load_last_brief_for_html(config: dict) -> dict | None:
    """Parse the most recent brief file and return data suitable for HTML rendering.

    Returns a dict with keys: summary, project_update, sources, generated_at (datetime).
    Returns None if no recent brief is found.
    """
    import ast

    for date_str, md_path, text in _iter_recent_briefs(config, days=30):
        # Parse frontmatter
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        frontmatter, body = parts[1], parts[2]

        sources = []
        generated_at = None
        for line in frontmatter.splitlines():
            if line.startswith("sources:"):
                try:
                    sources = ast.literal_eval(line[len("sources:"):].strip())
                except (ValueError, SyntaxError):
                    pass
            elif line.startswith("date:") and line[len("date:"):].strip():
                date_val = line[len("date:"):].strip()
            elif line.startswith("generated_at:") and line[len("generated_at:"):].strip():
                time_val = line[len("generated_at:"):].strip()

        try:
            generated_at = datetime.strptime(f"{date_val} {time_val}", "%Y-%m-%d %H:%M")
        except (ValueError, UnboundLocalError):
            generated_at = datetime.now()

        # Strip title line
        body = body.lstrip("\n")
        lines = body.splitlines()
        if lines and lines[0].startswith("# Intel Brief"):
            body = "\n".join(lines[1:]).lstrip("\n")

        # Split off My Notes section
        notes_marker = "\n---\n\n## My Notes"
        if notes_marker in body:
            body = body.split(notes_marker)[0]

        # Split off My ToDos section — rendered separately in the sidebar,
        # so we don't want it duplicated inline in the main brief.
        todos_marker = "\n## My ToDos"
        if todos_marker in body:
            body = body.split(todos_marker)[0]

        # Split project update from summary body
        project_update = ""
        proj_marker = "\n## Project Status Update"
        if proj_marker in body:
            summary_part, proj_part = body.split(proj_marker, 1)
            project_update = "## Project Status Update" + proj_part.rstrip()
            body = summary_part.rstrip()
        else:
            body = body.rstrip()

        return {
            "summary": body,
            "project_update": project_update,
            "sources": sources,
            "generated_at": generated_at,
            "md_path": md_path,
        }

    return None


def write_brief(summary: str, all_updates: dict, config: dict, project_update: str = "") -> Path:
    vault_path = get_vault_path(config)
    output_folder = config.get("obsidian_output_folder", "Intel Briefs")

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    output_dir = vault_path / output_folder / now.strftime("%Y%m")
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / (now.strftime("%d %H-%M") + ".md")

    # Strip any title heading the LLM may have added — the template provides it
    summary_body = "\n".join(
        line for i, line in enumerate(summary.splitlines())
        if not (i == 0 and line.startswith("# "))
    ).lstrip("\n")

    project_section = f"{project_update.strip()}\n\n" if project_update else ""

    # Carry forward unchecked todos from previous brief
    open_todos = load_open_todos(config)
    if open_todos:
        todos_lines = "\n".join(f"- [ ] {item}" for item in open_todos)
    else:
        todos_lines = _TODOS_PLACEHOLDER

    content = f"""---
date: {date_str}
generated_at: {time_str}
sources: {list(all_updates.keys())}
---

# Intel Brief — {date_str} {time_str}

{summary_body}

{project_section}## My ToDos
{todos_lines}

---

## My Notes
{_NOTES_PLACEHOLDER}
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"\n  Brief written to: {filepath}")
    return filepath


def write_meeting_prep(prep_text: str, config: dict) -> Path:
    """Write meeting prep notes to the Obsidian vault."""
    vault_path = get_vault_path(config)
    output_folder = config.get("obsidian_output_folder", "Intel Briefs")

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    output_dir = vault_path / output_folder / now.strftime("%Y%m")
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / (now.strftime("%d %H-%M") + " Meeting Prep.md")

    # Strip any title heading the LLM may have added
    prep_body = "\n".join(
        line for i, line in enumerate(prep_text.splitlines())
        if not (i == 0 and line.startswith("# "))
    ).lstrip("\n")

    content = f"""---
date: {date_str}
generated_at: {time_str}
type: meeting-prep
---

# Meeting Prep — {date_str}

{prep_body}
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"\n  Meeting prep written to: {filepath}")
    return filepath
