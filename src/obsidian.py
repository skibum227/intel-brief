import json
import os
from datetime import datetime
from pathlib import Path


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

    counts = {source: len(items) for source, items in all_updates.items()}

    def raw_block(key: str) -> str:
        label = key.replace("_", " ").title()
        data = json.dumps(all_updates.get(key, []), indent=2, default=str)
        return (
            f"<details>\n<summary>{label} ({counts.get(key, 0)} items)</summary>\n\n"
            f"```json\n{data}\n```\n\n</details>"
        )

    content = f"""---
date: {date_str}
generated_at: {time_str}
sources: {list(all_updates.keys())}
---

# Intel Brief — {date_str}

{summary}

---

## Raw Data

*Fetched at {time_str} — totals: {counts}*

{raw_block("slack")}

{raw_block("jira")}

{raw_block("confluence")}

{raw_block("google_cal")}

{raw_block("gmail")}
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"\n  Brief written to: {filepath}")
    return filepath
