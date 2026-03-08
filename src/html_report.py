import json
import os
import re
import socket
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


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

    return rf"""<!DOCTYPE html>
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
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}

    /* ── Lede ─────────────────────────────────────────────── */
    .brief-lede {{ padding: 0.25rem 0 0.5rem; }}
    .brief-lede p {{
      font-size: 1rem !important;
      color: #94a3b8 !important;
      line-height: 1.85 !important;
      font-weight: 400 !important;
      margin: 0 !important;
    }}
    html:not(.dark) .brief-lede p {{ color: #475569 !important; }}
    .lede-divider {{
      height: 1px;
      background: rgba(148,163,184,0.1);
      margin: 1.5rem 0 0.5rem;
    }}

    /* ── Prose ────────────────────────────────────────────── */
    .prose h2 {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.7rem;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #64748b;
      margin: 2.25rem 0 0.9rem;
      cursor: pointer;
      user-select: none;
    }}
    .prose h2::before {{
      content: '';
      display: inline-block;
      width: 3px;
      height: 0.9rem;
      border-radius: 2px;
      background: #6366f1;
      flex-shrink: 0;
      transition: opacity 0.15s;
    }}
    .prose h2.section-collapsed::before {{ opacity: 0.3; }}
    .prose h2::after {{
      content: '▾';
      font-size: 0.65rem;
      margin-left: auto;
      opacity: 0.3;
      transition: transform 0.15s, opacity 0.15s;
    }}
    .prose h2.section-collapsed::after {{ transform: rotate(-90deg); opacity: 0.2; }}
    #project-content .prose h2::before {{ background: #10b981; }}
    .prose h3 {{
      display: flex;
      align-items: center;
      gap: 0.45rem;
      font-size: 0.82rem;
      font-weight: 600;
      color: #94a3b8;
      margin: 1.75rem 0 0.5rem;
      letter-spacing: 0.01em;
    }}
    .prose h3::before {{
      content: '';
      display: inline-block;
      width: 2px;
      height: 0.75rem;
      border-radius: 2px;
      background: #6366f1;
      opacity: 0.5;
      flex-shrink: 0;
    }}
    #project-content .prose h3::before {{ background: #10b981; }}
    .prose p {{ color: #cbd5e1; line-height: 1.75; margin: 0.5rem 0; font-size: 0.9rem; }}
    .prose strong {{ color: #e2e8f0; font-weight: 600; }}
    .prose em {{ color: #94a3b8; font-style: italic; }}
    .prose ul {{ list-style: none; padding: 0; margin: 0.25rem 0 0.75rem; }}
    .prose li {{ color: #cbd5e1; line-height: 1.7; font-size: 0.9rem; padding: 0; position: relative; }}
    .prose li.plain-li {{ padding-left: 1.1rem; }}
    .prose li.plain-li::before {{ content: '–'; position: absolute; left: 0; color: #475569; font-weight: 300; }}
    .prose hr {{ border: none; border-top: 1px solid rgba(148,163,184,0.08); margin: 2rem 0; }}
    .prose code {{
      font-size: 0.8em;
      background: rgba(148,163,184,0.1);
      padding: 0.15em 0.4em;
      border-radius: 4px;
      color: #e2e8f0;
    }}
    .prose a {{ color: #818cf8; text-decoration: none; }}
    .prose a:hover {{ text-decoration: underline; }}

    html:not(.dark) .prose h2 {{ color: #94a3b8; }}
    html:not(.dark) .prose h3 {{ color: #475569; }}
    html:not(.dark) .prose p  {{ color: #334155; }}
    html:not(.dark) .prose strong {{ color: #1e293b; }}
    html:not(.dark) .prose li {{ color: #334155; }}
    html:not(.dark) .prose li.plain-li::before {{ color: #94a3b8; }}
    html:not(.dark) .prose code {{ background: rgba(71,85,105,0.08); color: #1e293b; }}
    html:not(.dark) .prose a {{ color: #6366f1; }}

    /* ── Task checkboxes ──────────────────────────────────── */
    .task-item {{
      display: flex;
      align-items: flex-start;
      gap: 0.6rem;
      padding: 0.3rem 0.5rem;
      margin: 0.15rem -0.5rem;
      border-radius: 7px;
      cursor: pointer;
      transition: background 0.1s;
      border-left: 2px solid transparent;
    }}
    .task-item:hover {{ background: rgba(148,163,184,0.06); }}
    .task-item.done .task-text {{ text-decoration: line-through; opacity: 0.32; }}
    .task-checkbox {{
      flex-shrink: 0;
      width: 15px;
      height: 15px;
      margin-top: 3px;
      border-radius: 4px;
      border: 1.5px solid rgba(148,163,184,0.3);
      background: transparent;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
    }}
    .task-item.done .task-checkbox {{
      background: #6366f1;
      border-color: #6366f1;
    }}
    .task-item.done .task-checkbox::after {{
      content: '';
      width: 8px;
      height: 4px;
      border-left: 1.5px solid white;
      border-bottom: 1.5px solid white;
      transform: rotate(-45deg) translateY(-1px);
      display: block;
    }}
    .task-text {{ font-size: 0.9rem; color: #cbd5e1; line-height: 1.65; }}
    html:not(.dark) .task-text {{ color: #334155; }}

    /* ── Urgency borders ──────────────────────────────────── */
    .task-item.urgency-red    {{ border-left-color: rgba(239,68,68,0.5);  padding-left: calc(0.5rem - 2px); }}
    .task-item.urgency-yellow {{ border-left-color: rgba(245,158,11,0.5); padding-left: calc(0.5rem - 2px); }}
    .task-item.urgency-green  {{ border-left-color: rgba(34,197,94,0.3);  padding-left: calc(0.5rem - 2px); }}

    /* ── Progress bar ─────────────────────────────────────── */
    .progress-track {{
      width: 44px; height: 4px; border-radius: 9999px;
      background: rgba(148,163,184,0.12); overflow: hidden;
    }}
    .progress-fill {{
      height: 100%; border-radius: 9999px;
      background: #6366f1; transition: width 0.4s ease;
    }}

    /* ── Sparkline ────────────────────────────────────────── */
    .sparkline {{ display: block; }}

    /* ── Next meeting chip ────────────────────────────────── */
    .meeting-chip {{
      display: inline-flex; align-items: center; gap: 5px;
      padding: 3px 10px 3px 8px; border-radius: 9999px;
      font-size: 0.71rem; font-weight: 500;
      background: rgba(99,102,241,0.1);
      border: 1px solid rgba(99,102,241,0.2);
      color: #818cf8;
      max-width: 260px; overflow: hidden;
      white-space: nowrap; text-overflow: ellipsis;
    }}
    html:not(.dark) .meeting-chip {{
      background: rgba(99,102,241,0.07);
      border-color: rgba(99,102,241,0.2);
      color: #6366f1;
    }}

    /* ── Sync toast ───────────────────────────────────────── */
    #sync-toast {{
      position: fixed; bottom: 1.5rem; right: 1.5rem;
      font-size: 0.75rem; padding: 0.4rem 0.9rem; border-radius: 8px;
      opacity: 0; transform: translateY(4px);
      transition: opacity 0.2s, transform 0.2s; pointer-events: none;
      background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.3); color: #34d399;
    }}
    #sync-toast.show {{ opacity: 1; transform: translateY(0); }}
    #sync-toast.error {{
      background: rgba(239,68,68,0.15); border-color: rgba(239,68,68,0.3); color: #f87171;
    }}

    /* ── Sidebar nav ──────────────────────────────────────── */
    .nav-section {{
      font-size: 0.65rem; font-weight: 700;
      letter-spacing: 0.1em; text-transform: uppercase;
      color: #334155; padding: 0.25rem 0.75rem; margin-top: 1rem;
    }}
    html:not(.dark) .nav-section {{ color: #94a3b8; }}
    .nav-link {{
      display: flex; align-items: flex-start; gap: 0.4rem;
      padding: 0.28rem 0.75rem; border-radius: 6px;
      font-size: 0.78rem; color: #475569;
      text-decoration: none; transition: all 0.12s;
      line-height: 1.4; word-break: break-word;
    }}
    .nav-link::before {{
      content: ''; width: 4px; height: 4px; border-radius: 50%;
      background: currentColor; flex-shrink: 0; opacity: 0.4;
      margin-top: 6px;
    }}
    html:not(.dark) .nav-link {{ color: #94a3b8; }}
    .nav-link:hover {{ background: rgba(148,163,184,0.08); color: #94a3b8; }}
    html:not(.dark) .nav-link:hover {{ color: #64748b; }}
    .nav-link.nav-active {{
      color: #818cf8; background: rgba(99,102,241,0.08); font-weight: 500;
    }}
    html:not(.dark) .nav-link.nav-active {{
      color: #6366f1; background: rgba(99,102,241,0.06);
    }}

    /* ── Source pills ─────────────────────────────────────── */
    .source-pill {{
      display: inline-flex; align-items: center; gap: 5px;
      padding: 4px 11px 4px 8px; border-radius: 9999px;
      font-size: 0.71rem; font-weight: 500; letter-spacing: 0.02em;
    }}
    .source-dot {{ width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }}

    /* ── Misc ─────────────────────────────────────────────── */
    ::-webkit-scrollbar {{ width: 4px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{ background: rgba(148,163,184,0.15); border-radius: 2px; }}
    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .fade-in        {{ animation: fadeUp 0.3s ease both; }}
    .fade-in-delay  {{ animation: fadeUp 0.35s ease 0.06s both; }}
    .fade-in-delay2 {{ animation: fadeUp 0.35s ease 0.12s both; }}
    .section-hidden {{ display: none !important; }}
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

  <!-- ── Layout ───────────────────────────────────────────────── -->
  <div class="max-w-6xl mx-auto px-4 md:px-6 py-8 flex gap-8">

    <!-- Sidebar -->
    <aside class="hidden lg:flex flex-col w-48 flex-shrink-0 sticky top-20 self-start max-h-[calc(100vh-6rem)] overflow-y-auto fade-in">
      <div id="nav-links"></div>
    </aside>

    <!-- Content -->
    <main class="flex-1 min-w-0 space-y-4">

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
  </div>

  <div id="sync-toast">Saved to Obsidian</div>

  <script>
    const BRIEF_MD        = `{summary_escaped}`;
    const PROJECT_MD      = `{project_escaped}`;
    const REPORT_KEY      = '{report_key}';
    const SYNC_PORT       = {sync_port};
    const SPARKLINE_DATA  = {sparkline_json};
    const NEXT_MEETING    = {next_meeting_json};

    marked.use({{ breaks: true, gfm: true }});

    // ── Theme ──────────────────────────────────────────────────────────────────
    function toggleTheme() {{
      const dark = document.documentElement.classList.toggle('dark');
      localStorage.setItem('intel-theme', dark ? 'dark' : 'light');
      document.getElementById('icon-sun').classList.toggle('hidden', dark);
      document.getElementById('icon-moon').classList.toggle('hidden', !dark);
    }}
    (function () {{
      const saved = localStorage.getItem('intel-theme');
      const dark = saved ? saved === 'dark' : true;
      document.documentElement.classList.toggle('dark', dark);
      document.getElementById('icon-sun').classList.toggle('hidden', dark);
      document.getElementById('icon-moon').classList.toggle('hidden', !dark);
    }})();

    // ── Checkbox state ─────────────────────────────────────────────────────────
    function getState() {{
      try {{ return JSON.parse(localStorage.getItem(REPORT_KEY) || '{{}}'); }}
      catch {{ return {{}}; }}
    }}
    function setState(s) {{ localStorage.setItem(REPORT_KEY, JSON.stringify(s)); }}

    // ── Sync toast ─────────────────────────────────────────────────────────────
    let toastTimer;
    function showSyncToast(ok, msg) {{
      const t = document.getElementById('sync-toast');
      t.textContent = ok ? 'Saved to Obsidian' : ('Sync failed: ' + msg);
      t.classList.toggle('error', !ok);
      t.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => t.classList.remove('show'), ok ? 2000 : 5000);
    }}

    // ── Sparkline ──────────────────────────────────────────────────────────────
    function renderSparkline(data) {{
      const svgEl = document.getElementById('sparkline');
      if (!svgEl || !data || data.length < 2) return;
      const w = 52, h = 22, pad = 2;
      const max = Math.max(...data, 1);
      const xStep = (w - pad * 2) / (data.length - 1);
      const pts = data.map((v, i) => {{
        const x = pad + i * xStep;
        const y = h - pad - (v / max) * (h - pad * 2);
        return `${{x.toFixed(1)}},${{y.toFixed(1)}}`;
      }}).join(' ');
      const last = data[data.length - 1];
      const lastX = (pad + (data.length - 1) * xStep).toFixed(1);
      const lastY = (h - pad - (last / max) * (h - pad * 2)).toFixed(1);
      svgEl.innerHTML = `
        <polyline points="${{pts}}" fill="none" stroke="#6366f1" stroke-width="1.5"
          stroke-linecap="round" stroke-linejoin="round" opacity="0.6"/>
        <circle cx="${{lastX}}" cy="${{lastY}}" r="2" fill="#6366f1" opacity="0.9"/>`;
      svgEl.classList.remove('hidden');
    }}

    // ── Next meeting widget ────────────────────────────────────────────────────
    function renderMeetingWidget() {{
      if (!NEXT_MEETING) return;
      const w = document.getElementById('meeting-widget');
      const att = NEXT_MEETING.attendees > 0 ? ` · ${{NEXT_MEETING.attendees}} attendees` : '';
      w.innerHTML = `<span class="meeting-chip">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
          <rect x="2" y="3" width="12" height="11" rx="2"/>
          <path stroke-linecap="round" d="M5 1v3M11 1v3M2 7h12"/>
        </svg>
        ${{NEXT_MEETING.title}} &middot; ${{NEXT_MEETING.when}}${{att}}
      </span>`;
      w.classList.remove('hidden');
    }}

    // ── Progress bar ───────────────────────────────────────────────────────────
    function updateProgress() {{
      const total = document.querySelectorAll('#brief-content .task-item').length;
      const done  = document.querySelectorAll('#brief-content .task-item.done').length;
      const fill  = document.getElementById('brief-progress-fill');
      const label = document.getElementById('brief-progress-label');
      if (fill)  fill.style.width  = total ? `${{Math.round((done / total) * 100)}}%` : '0%';
      if (label) label.textContent = `${{done}} / ${{total}}`;
    }}

    // ── Collapsible h2 sections ────────────────────────────────────────────────
    function makeCollapsible(el) {{
      el.querySelectorAll('h2').forEach(h => {{
        h.addEventListener('click', () => {{
          const collapsed = h.classList.toggle('section-collapsed');
          let next = h.nextElementSibling;
          while (next && next.tagName !== 'H2') {{
            next.classList.toggle('section-hidden', collapsed);
            next = next.nextElementSibling;
          }}
        }});
      }});
    }}

    // ── Active sidebar highlight ───────────────────────────────────────────────
    function setupActiveNav() {{
      const nav = document.getElementById('nav-links');
      if (!nav) return;
      const observer = new IntersectionObserver(entries => {{
        entries.forEach(entry => {{
          const link = nav.querySelector(`a[href="#${{entry.target.id}}"]`);
          if (link) link.classList.toggle('nav-active', entry.isIntersecting);
        }});
      }}, {{ rootMargin: '-15% 0px -70% 0px', threshold: 0 }});
      document.querySelectorAll('h2[id], h3[id]').forEach(h => observer.observe(h));
    }}

    // ── Process rendered markdown ──────────────────────────────────────────────
    function processContent(el, keyPrefix, startSyncIdx, enableSync) {{
      const state = getState();
      let syncIdx = startSyncIdx;

      el.querySelectorAll('li').forEach((li, i) => {{
        const inputEl = li.querySelector('input[type="checkbox"]');
        if (!inputEl) {{
          li.classList.add('plain-li');
          return;
        }}
        const isChecked = inputEl.checked;
        const cbSyncIdx = syncIdx++;
        const key = keyPrefix + '-' + i;
        const done = state[key] !== undefined ? state[key] : isChecked;

        inputEl.remove();
        const inner = li.innerHTML.trim();

        li.innerHTML = '';
        li.style.cssText = 'list-style:none;padding:0';

        const wrap = document.createElement('div');
        wrap.className = 'task-item' + (done ? ' done' : '');

        // Urgency border
        const text = inner.replace(/<[^>]+>/g, '');
        if (text.includes('🔴')) wrap.classList.add('urgency-red');
        else if (text.includes('🟡')) wrap.classList.add('urgency-yellow');
        else if (text.includes('🟢')) wrap.classList.add('urgency-green');

        const box = document.createElement('div');
        box.className = 'task-checkbox';

        const txt = document.createElement('span');
        txt.className = 'task-text';
        txt.innerHTML = inner;

        wrap.append(box, txt);
        li.appendChild(wrap);

        wrap.addEventListener('click', () => {{
          const s = getState();
          const nowDone = !wrap.classList.contains('done');
          wrap.classList.toggle('done', nowDone);
          s[key] = nowDone;
          setState(s);
          updateProgress();

          if (enableSync && SYNC_PORT) {{
            console.log(`[sync] POST index=${{cbSyncIdx}} checked=${{nowDone}} → http://127.0.0.1:${{SYNC_PORT}}/sync`);
            fetch(`http://127.0.0.1:${{SYNC_PORT}}/sync`, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{ index: cbSyncIdx, checked: nowDone }}),
            }})
            .then(r => r.json().then(body => {{
              console.log('[sync] response:', r.status, body);
              if (r.ok) showSyncToast(true);
              else showSyncToast(false, body.error || r.status);
            }}))
            .catch(err => {{
              console.error('[sync] fetch error:', err);
              showSyncToast(false, err.message || 'network error');
            }});
          }}
        }});
      }});

      el.querySelectorAll('h2').forEach(h => {{
        h.id = h.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
      }});
      el.querySelectorAll('h3').forEach(h => {{
        if (!h.id) h.id = h.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-');
      }});

      return syncIdx;
    }}

    // ── Extract executive summary lede ─────────────────────────────────────────
    function extractLede(el) {{
      const firstH2 = el.querySelector('h2');
      if (!firstH2) return;
      const toMove = [];
      let node = el.firstChild;
      while (node && node !== firstH2) {{ toMove.push(node); node = node.nextSibling; }}
      if (!toMove.length) return;
      const ledeDiv = document.createElement('div');
      ledeDiv.className = 'brief-lede';
      toMove.forEach(n => ledeDiv.appendChild(n));
      el.insertBefore(ledeDiv, el.firstChild);
      const divider = document.createElement('div');
      divider.className = 'lede-divider';
      el.insertBefore(divider, ledeDiv.nextSibling);
    }}

    // ── Sidebar nav ────────────────────────────────────────────────────────────
    function buildNav() {{
      const nav = document.getElementById('nav-links');
      const briefH2s = document.querySelectorAll('#brief-content h2');
      if (briefH2s.length) {{
        const lbl = document.createElement('p');
        lbl.className = 'nav-section'; lbl.textContent = 'Brief';
        nav.appendChild(lbl);
        briefH2s.forEach(h => {{
          if (!h.id) return;
          nav.appendChild(Object.assign(document.createElement('a'), {{
            href: '#' + h.id, className: 'nav-link', textContent: h.textContent.trim(),
          }}));
        }});
      }}
      const projH = document.querySelectorAll('#project-content h2, #project-content h3');
      if (projH.length) {{
        const lbl = document.createElement('p');
        lbl.className = 'nav-section'; lbl.textContent = 'Projects';
        nav.appendChild(lbl);
        projH.forEach(h => {{
          if (!h.id) return;
          nav.appendChild(Object.assign(document.createElement('a'), {{
            href: '#' + h.id, className: 'nav-link', textContent: h.textContent.trim(),
          }}));
        }});
      }}
    }}

    // ── Render ─────────────────────────────────────────────────────────────────
    (function () {{
      const briefEl = document.getElementById('brief-content');
      briefEl.innerHTML = marked.parse(BRIEF_MD);
      extractLede(briefEl);
      let nextSyncIdx = processContent(briefEl, REPORT_KEY + '-brief', 0, true);
      makeCollapsible(briefEl);
      updateProgress();

      if (PROJECT_MD.trim()) {{
        const body = PROJECT_MD.replace(/^##[^\n]*\n/m, '');
        const projEl = document.getElementById('project-content');
        projEl.innerHTML = marked.parse(body);
        processContent(projEl, REPORT_KEY + '-proj', nextSyncIdx, false);
        makeCollapsible(projEl);
        document.getElementById('project-card').classList.remove('hidden');
      }}

      buildNav();
      setupActiveNav();
      renderSparkline(SPARKLINE_DATA);
      renderMeetingWidget();
    }})();
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
