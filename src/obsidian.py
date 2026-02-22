import os
from datetime import datetime, timedelta
from pathlib import Path


def load_recent_summaries(config: dict, days: int = 3) -> str:
    """Return the LLM-generated summary sections from the last `days` brief files."""
    vault_path = Path(
        os.path.expanduser(config.get("obsidian_vault_path", "~/Documents/ObsidianVault"))
    )
    output_dir = vault_path / config.get("obsidian_output_folder", "Intel Briefs")
    if not output_dir.exists():
        return ""

    cutoff = (datetime.now() - timedelta(days=days)).date()
    briefs = sorted(output_dir.glob("????-??-??.md"), reverse=True)

    sections = []
    for path in briefs:
        try:
            date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if date < cutoff:
            break

        text = path.read_text(encoding="utf-8")
        # Strip frontmatter (between first two --- delimiters)
        parts = text.split("---", 2)
        body = parts[2] if len(parts) >= 3 else text
        # Strip raw data block (everything from the separator before ## Raw Data)
        raw_marker = "\n---\n\n## Raw Data"
        if raw_marker in body:
            body = body.split(raw_marker)[0]
        sections.append(f"### {path.stem}\n{body.strip()}")

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
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"\n  Brief written to: {filepath}")
    return filepath
