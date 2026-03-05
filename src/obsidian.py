import os
from datetime import datetime, timedelta
from pathlib import Path

_NOTES_PLACEHOLDER = "<!-- Add your notes here. They will be read into tomorrow's brief. -->"


def _iter_recent_briefs(config: dict, days: int):
    """Yield (date, text) for brief files within the last `days` days."""
    vault_path = Path(
        os.path.expanduser(config.get("obsidian_vault_path", "~/Documents/ObsidianVault"))
    )
    output_dir = vault_path / config.get("obsidian_output_folder", "Intel Briefs")
    if not output_dir.exists():
        return

    cutoff = (datetime.now() - timedelta(days=days)).date()
    for path in sorted(output_dir.glob("????-??-??.md"), reverse=True):
        try:
            date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if date < cutoff:
            break
        yield path.stem, path.read_text(encoding="utf-8")


def load_recent_summaries(config: dict, days: int = 3) -> str:
    """Return the LLM-generated summary sections from the last `days` brief files."""
    sections = []
    for stem, text in _iter_recent_briefs(config, days):
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
        sections.append(f"### {stem}\n{body.strip()}")

    return "\n\n".join(sections)


def load_user_notes(config: dict, days: int = 3) -> str:
    """Return user-written notes from the last `days` brief files."""
    sections = []
    for stem, text in _iter_recent_briefs(config, days):
        notes_marker = "\n---\n\n## My Notes"
        if notes_marker not in text:
            continue
        notes_text = text.split(notes_marker, 1)[1].strip()
        # Skip empty or placeholder-only sections
        cleaned = notes_text.replace(_NOTES_PLACEHOLDER, "").strip()
        if not cleaned:
            continue
        sections.append(f"### {stem}\n{cleaned}")

    return "\n\n".join(sections)


def write_brief(summary: str, all_updates: dict, config: dict) -> Path:
    vault_path = Path(
        os.path.expanduser(config.get("obsidian_vault_path", "~/Documents/ObsidianVault"))
    )
    output_folder = config.get("obsidian_output_folder", "Intel Briefs")
    output_dir = vault_path / output_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    filepath = output_dir / f"{date_str}.md"

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

# Intel Brief — {date_str}

{summary_body}

---

## My Notes
{_NOTES_PLACEHOLDER}
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"\n  Brief written to: {filepath}")
    return filepath
