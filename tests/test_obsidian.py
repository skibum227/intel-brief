"""
Tests for src.obsidian helpers that affect HTML rendering.

Focused on load_last_brief_for_html: the body it returns is what gets
rendered into the main HTML brief area, and we never want the My ToDos
section to appear there (sidebar already shows it).
"""
from datetime import datetime
from pathlib import Path

import pytest

from src import obsidian


def _write_brief(tmp_path: Path, body: str, when: datetime) -> Path:
    """Helper: write a brief markdown file in the layout obsidian expects."""
    folder = tmp_path / "Intel Briefs" / when.strftime("%Y%m")
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / (when.strftime("%d %H-%M") + ".md")
    f.write_text(body, encoding="utf-8")
    return f


def _config(tmp_path: Path) -> dict:
    return {
        "obsidian_vault_path": str(tmp_path),
        "obsidian_output_folder": "Intel Briefs",
    }


def test_load_strips_todos_from_main_body(tmp_path):
    when = datetime.now()
    md = f"""---
date: {when.strftime('%Y-%m-%d')}
generated_at: {when.strftime('%H:%M')}
sources: ['slack']
---

# Intel Brief — {when.strftime('%Y-%m-%d')} {when.strftime('%H:%M')}

Today the team shipped X.

## Project Pulse
- [ ] Real item

## My ToDos
- [ ] should not appear in HTML body
- [x] also should not appear

---

## My Notes
some notes
"""
    _write_brief(tmp_path, md, when)
    out = obsidian.load_last_brief_for_html(_config(tmp_path))
    assert out is not None
    assert "## My ToDos" not in out["summary"]
    assert "should not appear" not in out["summary"]
    # The real content survives
    assert "Project Pulse" in out["summary"]
    assert "Real item" in out["summary"]


def test_load_strips_todos_when_project_update_present(tmp_path):
    when = datetime.now()
    md = f"""---
date: {when.strftime('%Y-%m-%d')}
generated_at: {when.strftime('%H:%M')}
sources: ['slack']
---

# Intel Brief — {when.strftime('%Y-%m-%d')} {when.strftime('%H:%M')}

Body summary text.

## Priorities & Action Items
- [ ] do thing

## Project Status Update

### Data Science
- **X**: status

## My ToDos
- [ ] sidebar-only item

---

## My Notes
"""
    _write_brief(tmp_path, md, when)
    out = obsidian.load_last_brief_for_html(_config(tmp_path))
    assert out is not None
    # Neither summary nor project_update should bleed the ToDos section
    assert "## My ToDos" not in out["summary"]
    assert "## My ToDos" not in out["project_update"]
    assert "sidebar-only item" not in out["summary"]
    assert "sidebar-only item" not in out["project_update"]
    # Project update content is intact
    assert "Project Status Update" in out["project_update"]
    assert "Data Science" in out["project_update"]


def test_load_open_todos_still_reads_from_disk(tmp_path):
    """Sanity: the markdown file still keeps ToDos so the sidebar can load them."""
    when = datetime.now()
    md = f"""---
date: {when.strftime('%Y-%m-%d')}
generated_at: {when.strftime('%H:%M')}
sources: ['slack']
---

# Intel Brief — x

Body.

## My ToDos
- [ ] keep me
- [x] done

---

## My Notes
"""
    _write_brief(tmp_path, md, when)
    todos = obsidian.load_open_todos(_config(tmp_path))
    assert todos == ["keep me"]
