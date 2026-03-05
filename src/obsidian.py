import os
from datetime import datetime, timedelta
from pathlib import Path

_NOTES_PLACEHOLDER = "<!-- Add your notes here. They will be read into tomorrow's brief. -->"

_CHECKBOX_SECTIONS = {"Project Pulse", "Priorities & Action Items", "Who Needs a Response"}


def _iter_recent_briefs(config: dict, days: int):
    """Yield (date_str, text) for brief files within the last `days` days."""
    vault_path = Path(
        os.path.expanduser(config.get("obsidian_vault_path", "~/Documents/ObsidianVault"))
    )
    output_dir = vault_path / config.get("obsidian_output_folder", "Intel Briefs")
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
        yield dt.strftime("%Y-%m-%d %H:%M"), path.read_text(encoding="utf-8")


def load_recent_summaries(config: dict, days: int = 3) -> str:
    """Return the LLM-generated summary sections from the last `days` brief files."""
    sections = []
    for date_str, text in _iter_recent_briefs(config, days):
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
    for date_str, text in _iter_recent_briefs(config, days):
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


def load_completed_items(config: dict, days: int = 3) -> str:
    """Return checked-off items from the three checkbox sections of recent briefs."""
    completed = []
    for date_str, text in _iter_recent_briefs(config, days):
        current_section = None
        for line in text.splitlines():
            if line.startswith("## "):
                section_name = line[3:].strip()
                current_section = section_name if section_name in _CHECKBOX_SECTIONS else None
            elif current_section and line.startswith("- [x]"):
                item_text = line[len("- [x]"):].strip()
                completed.append(f"- {item_text} ({date_str})")

    return "\n".join(completed)


def write_brief(summary: str, all_updates: dict, config: dict) -> Path:
    vault_path = Path(
        os.path.expanduser(config.get("obsidian_vault_path", "~/Documents/ObsidianVault"))
    )
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

    content = f"""---
date: {date_str}
generated_at: {time_str}
sources: {list(all_updates.keys())}
---

# Intel Brief — {date_str} {time_str}

{summary_body}

---

## My Notes
{_NOTES_PLACEHOLDER}
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"\n  Brief written to: {filepath}")
    return filepath
