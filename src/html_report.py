import json
import os
import re
import socket
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from src.dismissed import add_dismissed


_SOURCE_STYLES = {
    "slack":      ("Slack",      "rgba(167,139,250,0.15)", "#c4b5fd"),
    "jira":       ("Jira",       "rgba(96,165,250,0.15)",  "#93c5fd"),
    "confluence": ("Confluence", "rgba(45,212,191,0.15)",  "#5eead4"),
    "google_cal": ("Calendar",   "rgba(74,222,128,0.15)",  "#86efac"),
    "gmail":      ("Gmail",      "rgba(248,113,113,0.15)", "#fca5a5"),
    "github":     ("GitHub",     "rgba(148,163,184,0.12)", "#94a3b8"),
}


def _source_strip_html(all_updates: dict) -> str:
    pills = []
    for key, (label, bg, color) in _SOURCE_STYLES.items():
        count = len(all_updates.get(key, []))
        pills.append(
            f'<span class="source-pill" style="background:{bg};color:{color}">'
            f'<span class="source-dot" style="background:{color}"></span>'
            f'{label}&nbsp;<span style="opacity:0.55;font-weight:400">{count}</span></span>'
        )
    return "\n      ".join(pills)


def _find_free_port(preferred: int = 15173) -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", preferred))
            return preferred
    except OSError:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _toggle_checkbox(md_path: Path, index: int, checked: bool) -> None:
    """Toggle the Nth - [ ] / - [x] line in the markdown file.

    Uses atomic os.replace so the file is never left in a truncated state,
    and a retry loop to handle Obsidian's file-watcher briefly overwriting
    the file when it detects an external change.
    """
    import time

    for attempt in range(5):
        lines = md_path.read_text(encoding="utf-8").splitlines(keepends=True)
        n = 0
        for i, line in enumerate(lines):
            if re.match(r"- \[[ x]\]", line, re.IGNORECASE):
                if n == index:
                    if checked:
                        lines[i] = re.sub(r"\[ \]", "[x]", line, count=1)
                    else:
                        lines[i] = re.sub(r"\[x\]", "[ ]", line, count=1, flags=re.IGNORECASE)
                    # Atomic write: temp file + rename so we never truncate mid-read
                    tmp = md_path.with_suffix(".intel-tmp")
                    tmp.write_text("".join(lines), encoding="utf-8")
                    os.replace(tmp, md_path)
                    print(f"  ✓ Obsidian sync: checkbox {index} → {'[x]' if checked else '[ ]'} ({md_path.name})")
                    return
                n += 1  # advance counter for each checkbox found

        if n == 0 and attempt < 4:
            # File was empty/truncated mid-write by Obsidian — wait and retry
            delay = 0.15 * (attempt + 1)
            print(f"  ⟳ file appears truncated (attempt {attempt + 1}), retrying in {delay:.2f}s...")
            time.sleep(delay)
            continue
        break

    print(f"  ✗ Obsidian sync: checkbox index {index} not found in {md_path.name} ({n} total)")


_NOTES_SECTION = "\n---\n\n## My Notes\n"
_NOTES_PLACEHOLDER = "<!-- Add your notes here. They will be read into tomorrow's brief. -->"
_TODOS_SECTION = "\n## My ToDos\n"
_TODOS_PLACEHOLDER = "<!-- Add tasks here. Unchecked items carry forward to the next brief. -->"


def _read_notes(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    if _NOTES_SECTION not in text:
        return ""
    return text.split(_NOTES_SECTION, 1)[1].replace(_NOTES_PLACEHOLDER, "").strip()


def _save_notes(md_path: Path, notes_text: str) -> None:
    text = md_path.read_text(encoding="utf-8")
    content = notes_text.strip() if notes_text.strip() else _NOTES_PLACEHOLDER
    if _NOTES_SECTION in text:
        before = text.split(_NOTES_SECTION, 1)[0]
        new_text = before + _NOTES_SECTION + content + "\n"
    else:
        new_text = text.rstrip() + _NOTES_SECTION + content + "\n"
    tmp = md_path.with_suffix(".intel-tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, md_path)
    print(f"  ✓ Notes saved to Obsidian ({md_path.name})")


def _read_todos(md_path: Path) -> list[dict]:
    """Read todo items from the My ToDos section. Returns [{text, checked}, ...]."""
    text = md_path.read_text(encoding="utf-8")
    if _TODOS_SECTION not in text:
        return []
    todos_text = text.split(_TODOS_SECTION, 1)[1]
    # Stop at the next section boundary
    for boundary in ("\n---\n", "\n## "):
        if boundary in todos_text:
            todos_text = todos_text.split(boundary, 1)[0]
    items = []
    for line in todos_text.splitlines():
        if line.startswith("- [x]"):
            items.append({"text": line[5:].strip(), "checked": True})
        elif line.startswith("- [ ]"):
            items.append({"text": line[5:].strip(), "checked": False})
    return items


def _save_todos(md_path: Path, todos: list[dict]) -> None:
    """Write todo items back to the My ToDos section."""
    text = md_path.read_text(encoding="utf-8")
    if todos:
        lines = []
        for item in todos:
            mark = "x" if item.get("checked") else " "
            lines.append(f"- [{mark}] {item['text']}")
        content = "\n".join(lines)
    else:
        content = _TODOS_PLACEHOLDER

    if _TODOS_SECTION in text:
        before = text.split(_TODOS_SECTION, 1)[0]
        after_section = text.split(_TODOS_SECTION, 1)[1]
        # Find the end of the todos section (next --- or ## boundary)
        remainder = ""
        for boundary in ("\n---\n", "\n## "):
            if boundary in after_section:
                idx = after_section.index(boundary)
                remainder = after_section[idx:]
                break
        new_text = before + _TODOS_SECTION + content + "\n" + remainder
    else:
        # Insert before My Notes section
        if _NOTES_SECTION in text:
            before = text.split(_NOTES_SECTION, 1)[0]
            new_text = before + _TODOS_SECTION + content + "\n" + _NOTES_SECTION + text.split(_NOTES_SECTION, 1)[1]
        else:
            new_text = text.rstrip() + "\n" + _TODOS_SECTION + content + "\n"

    tmp = md_path.with_suffix(".intel-tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, md_path)


def _make_handler(html_bytes: bytes, md_path: Path | None):
    class _Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self._cors()
                self.end_headers()
                self.wfile.write(html_bytes)
            elif self.path == "/ping":
                payload = json.dumps({
                    "ok": True,
                    "md_path": str(md_path) if md_path else None,
                    "md_exists": md_path.exists() if md_path else False,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors()
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/notes":
                notes = _read_notes(md_path) if md_path else ""
                payload = json.dumps({"notes": notes}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors()
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/todos":
                todos = _read_todos(md_path) if md_path else []
                payload = json.dumps({"todos": todos}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._cors()
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/sync":
                if md_path is None:
                    print("  ✗ Sync skipped: no md_path (re-render with --render-html to attach a file)")
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(b'{"error":"no md_path"}')
                    return
                length = int(self.headers.get("Content-Length", 0))
                try:
                    data = json.loads(self.rfile.read(length))
                    _toggle_checkbox(md_path, data["index"], data["checked"])
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                except Exception as e:
                    print(f"  ✗ Sync error: {e}")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/notes":
                if md_path is None:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(b'{"error":"no md_path"}')
                    return
                length = int(self.headers.get("Content-Length", 0))
                try:
                    data = json.loads(self.rfile.read(length))
                    _save_notes(md_path, data.get("notes", ""))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/todos":
                if md_path is None:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(b'{"error":"no md_path"}')
                    return
                length = int(self.headers.get("Content-Length", 0))
                try:
                    data = json.loads(self.rfile.read(length))
                    _save_todos(md_path, data.get("todos", []))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/dismiss":
                length = int(self.headers.get("Content-Length", 0))
                try:
                    data = json.loads(self.rfile.read(length))
                    fingerprint = data.get("fingerprint", "")
                    if fingerprint:
                        add_dismissed(fingerprint)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self._cors()
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):
            pass

    return _Handler


def _extract_next_meeting(all_updates: dict, now: datetime) -> dict | None:
    events = all_updates.get("google_cal", [])
    now_aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    for event in events:
        start_str = event.get("start", "")
        if not start_str or "T" not in start_str:
            continue
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if start_dt <= now_aware:
                continue
            mins = int((start_dt - now_aware).total_seconds() / 60)
            if mins < 60:
                when = f"in {mins}m"
            elif mins < 120:
                when = f"in {mins // 60}h {mins % 60}m"
            else:
                when = start_dt.strftime("%-I:%M %p")
            return {
                "title": event.get("title", "(No title)"),
                "when": when,
                "attendees": len(event.get("attendees", [])),
            }
        except (ValueError, TypeError):
            continue
    return None


def _build_html(
    summary: str,
    all_updates: dict,
    lookback_hours: float,
    now: datetime,
    project_update: str,
    sync_port: int,
    sparkline_data: list[int],
    next_meeting: dict | None,
    prev_fingerprints: list[str] = None,
) -> str:
    date_str = now.strftime("%A, %B %-d, %Y")
    time_str = now.strftime("%I:%M %p").lstrip("0")
    total_updates = sum(len(v) for v in all_updates.values())
    lookback_display = f"{lookback_hours:.1f}h window" if lookback_hours is not None else "cached"
    source_strip = _source_strip_html(all_updates)
    report_key = now.strftime("intel-brief-%Y%m%d-%H%M")

    def js_escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    summary_escaped = js_escape(summary)
    project_escaped = js_escape(project_update) if project_update else ""
    sparkline_json = json.dumps(sparkline_data)
    next_meeting_json = json.dumps(next_meeting) if next_meeting else "null"
    prev_fp_json = json.dumps(prev_fingerprints if prev_fingerprints is not None else [])

    _TEMPLATES_DIR = Path(__file__).parent / "templates"
    css_text = (_TEMPLATES_DIR / "brief.css").read_text(encoding="utf-8")
    js_text = (_TEMPLATES_DIR / "brief.js").read_text(encoding="utf-8")

    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Intel Brief — {date_str}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{ extend: {{ fontFamily: {{ sans: ['Inter', 'system-ui', 'sans-serif'] }} }} }}
    }}
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
{css_text}
  </style>
</head>
<body class="dark:bg-[#0f1117] bg-slate-50 min-h-screen font-sans transition-colors duration-200">

  <!-- ── Header ───────────────────────────────────────────────── -->
  <header class="sticky top-0 z-50 dark:bg-[#0f1117]/95 bg-white/95 backdrop-blur-md border-b dark:border-slate-800/60 border-slate-200 px-6 py-3.5">
    <div class="max-w-6xl mx-auto flex items-center justify-between gap-4">
      <div class="flex items-center gap-3 min-w-0">
        <div class="flex items-center gap-2.5">
          <div class="w-2 h-2 rounded-full bg-indigo-500 shadow-[0_0_6px_rgba(99,102,241,0.6)] animate-pulse"></div>
          <span class="text-sm font-semibold dark:text-white text-slate-900 tracking-tight">Intel Brief</span>
        </div>
        <span class="dark:text-slate-700 text-slate-300 select-none">/</span>
        <span class="text-sm dark:text-slate-400 text-slate-500 truncate">{date_str}</span>
        <span class="hidden sm:inline text-xs dark:text-slate-600 text-slate-400">{time_str}</span>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <span class="text-xs dark:text-slate-500 text-slate-400 dark:bg-slate-800/60 bg-slate-100 px-2.5 py-1 rounded-full border dark:border-slate-700/40 border-slate-200">{lookback_display}</span>
        <span class="text-xs dark:text-slate-500 text-slate-400 dark:bg-slate-800/60 bg-slate-100 px-2.5 py-1 rounded-full border dark:border-slate-700/40 border-slate-200">{total_updates} items</span>
        <button onclick="toggleTheme()"
          class="w-8 h-8 flex items-center justify-center rounded-lg dark:text-slate-600 text-slate-400 dark:hover:bg-slate-800 hover:bg-slate-100 transition-colors ml-0.5"
          title="Toggle theme">
          <svg id="icon-sun" class="hidden w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
            <circle cx="12" cy="12" r="4.5"/>
            <path stroke-linecap="round" d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
          </svg>
          <svg id="icon-moon" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75">
            <path stroke-linecap="round" d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        </button>
      </div>
    </div>
  </header>

  <!-- ── Source + next-meeting strip ─────────────────────────── -->
  <div class="dark:bg-[#0f1117] bg-white border-b dark:border-slate-800/40 border-slate-200/80 px-6 py-2">
    <div class="max-w-6xl mx-auto flex items-center gap-1.5 flex-wrap">
      {source_strip}
      <div id="meeting-widget" class="ml-auto hidden"></div>
    </div>
  </div>

  <!-- ── Layout: two-column ────────────────────────────────────── -->
  <div class="mx-auto px-4 md:px-6 py-8 flex gap-6" style="max-width: calc(72rem + 22rem + 1.5rem)">

    <!-- Left: Brief content -->
    <main class="min-w-0 space-y-4" style="width: 72rem; flex-shrink: 1">

      <!-- Daily Brief card -->
      <div class="dark:bg-[#161b27] bg-white rounded-2xl border dark:border-slate-800/60 border-slate-200 shadow-sm overflow-hidden border-t-2 border-t-indigo-500/70 fade-in-delay">
        <div class="px-6 py-4 border-b dark:border-slate-800/50 border-slate-100 flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <div class="w-1.5 h-5 rounded-full bg-indigo-500/70"></div>
            <div>
              <h1 class="text-sm font-semibold dark:text-slate-100 text-slate-800">Today's Brief</h1>
              <p class="text-xs dark:text-slate-500 text-slate-400 mt-0.5">{date_str} &middot; {time_str}</p>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <svg id="sparkline" class="sparkline hidden" width="52" height="22" viewBox="0 0 52 22"></svg>
            <div class="flex items-center gap-1.5">
              <span id="brief-progress-label" class="text-xs dark:text-slate-600 text-slate-400 tabular-nums">0 / 0</span>
              <div class="progress-track">
                <div id="brief-progress-fill" class="progress-fill" style="width:0%"></div>
              </div>
            </div>
          </div>
        </div>
        <div id="brief-content" class="prose px-6 py-6"></div>
      </div>

      <!-- Project Update card -->
      <div id="project-card" class="hidden dark:bg-[#161b27] bg-white rounded-2xl border dark:border-slate-800/60 border-slate-200 shadow-sm overflow-hidden border-t-2 border-t-emerald-500/70 fade-in-delay2">
        <div class="px-6 py-4 border-b dark:border-slate-800/50 border-slate-100 flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <div class="w-1.5 h-5 rounded-full bg-emerald-500/70"></div>
            <div>
              <h1 class="text-sm font-semibold dark:text-slate-100 text-slate-800">Project Status Update</h1>
              <p class="text-xs dark:text-slate-500 text-slate-400 mt-0.5">Weekly rollup across all teams</p>
            </div>
          </div>
          <span class="text-xs text-emerald-400 bg-emerald-900/20 px-2 py-0.5 rounded-md border border-emerald-800/30 font-medium">Weekly</span>
        </div>
        <div id="project-content" class="prose px-6 py-6"></div>
      </div>

      <p class="text-xs dark:text-slate-700 text-slate-300 text-center py-3">
        Generated {date_str} at {time_str}
      </p>
    </main>

    <!-- Right: Sticky sidebar — ToDos + Notes -->
    <aside class="hidden lg:flex flex-col flex-shrink-0 sticky top-20 self-start max-h-[calc(100vh-6rem)] overflow-y-auto space-y-4 fade-in" style="width: 22rem">

      <!-- My ToDos card -->
      <div class="dark:bg-[#161b27] bg-white rounded-2xl border dark:border-slate-800/60 border-slate-200 shadow-sm overflow-hidden border-t-2 border-t-cyan-500/70">
        <div class="px-4 py-3 border-b dark:border-slate-800/50 border-slate-100 flex items-center gap-2.5">
          <div class="w-1.5 h-5 rounded-full bg-cyan-500/70"></div>
          <h2 class="text-sm font-semibold dark:text-slate-100 text-slate-800">My ToDos</h2>
        </div>
        <div class="px-4 py-3">
          <div id="todos-list" class="todos-container space-y-1 text-sm"></div>
          <div class="mt-3 flex gap-2">
            <input id="todo-input" type="text"
              class="flex-1 text-sm dark:bg-slate-800/60 bg-slate-50 border dark:border-slate-700/50 border-slate-200 rounded-lg px-3 py-1.5 dark:text-slate-200 text-slate-800 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-cyan-500/50"
              placeholder="Add a task..." />
            <button onclick="addTodo()"
              class="text-xs font-medium px-3 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 transition-colors flex-shrink-0">
              Add
            </button>
          </div>
        </div>
      </div>

      <!-- My Notes card -->
      <div class="dark:bg-[#161b27] bg-white rounded-2xl border dark:border-slate-800/60 border-slate-200 shadow-sm overflow-hidden border-t-2 border-t-amber-500/60">
        <div class="px-4 py-3 border-b dark:border-slate-800/50 border-slate-100 flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <div class="w-1.5 h-5 rounded-full bg-amber-500/70"></div>
            <h2 class="text-sm font-semibold dark:text-slate-100 text-slate-800">My Notes</h2>
          </div>
          <button id="notes-save-btn" onclick="saveNotes()"
            class="text-xs font-medium px-2.5 py-1 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition-colors">
            Save
          </button>
        </div>
        <div class="px-4 py-3">
          <textarea id="notes-input" class="sidebar-notes-textarea"
            placeholder="Corrections, context, observations — feeds into tomorrow's brief..."></textarea>
        </div>
      </div>
    </aside>
  </div>

  <div id="sync-toast">Saved to Obsidian</div>

  <script>
    const CONFIG = {{
      BRIEF_MD:          `{summary_escaped}`,
      PROJECT_MD:        `{project_escaped}`,
      REPORT_KEY:        '{report_key}',
      SYNC_PORT:         {sync_port},
      SPARKLINE_DATA:    {sparkline_json},
      NEXT_MEETING:      {next_meeting_json},
      PREV_FINGERPRINTS: {prev_fp_json},
    }};
  </script>
  <script>
{js_text}
  </script>
</body>
</html>"""


def write_html_report(
    summary: str,
    all_updates: dict,
    config: dict,
    lookback_hours: float,
    now: datetime,
    project_update: str = "",
    md_path: Path | None = None,
    prev_fingerprints: list[str] = None,
) -> tuple[Path, HTTPServer]:
    from src.obsidian import load_daily_completion_counts

    vault_path = Path(
        os.path.expanduser(config.get("obsidian_vault_path", "~/Documents/ObsidianVault"))
    )
    output_folder = config.get("obsidian_output_folder", "Intel Briefs")
    output_dir = vault_path / output_folder / now.strftime("%Y%m")
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / (now.strftime("%d %H-%M") + ".html")

    sparkline_data = load_daily_completion_counts(config, days=7)
    next_meeting = _extract_next_meeting(all_updates, now)

    port = _find_free_port()
    html = _build_html(
        summary, all_updates, lookback_hours, now, project_update,
        sync_port=port, sparkline_data=sparkline_data, next_meeting=next_meeting,
        prev_fingerprints=prev_fingerprints,
    )
    html_bytes = html.encode("utf-8")
    filepath.write_text(html, encoding="utf-8")
    print(f"  HTML report written to: {filepath}")

    handler = _make_handler(html_bytes, md_path)
    HTTPServer.allow_reuse_address = True
    httpd = HTTPServer(("127.0.0.1", port), handler)
    print(f"  Sync port:  {port}")
    print(f"  Sync file:  {md_path}")
    print(f"  Ping check: http://127.0.0.1:{port}/ping")
    webbrowser.open(f"http://127.0.0.1:{port}/")
    return filepath, httpd
