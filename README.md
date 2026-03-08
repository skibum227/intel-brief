# intel-brief

Fetches updates from Slack, Jira, Confluence, Google Calendar, Gmail, and GitHub, then writes an AI-summarized brief into your Obsidian vault — with an optional live HTML dashboard that syncs checkboxes back to Obsidian.

```bash
python run.py                         # daily brief → Obsidian
python run.py --html                  # brief + live HTML dashboard (opens in browser)
python run.py --project-update        # brief + weekly project status section
python run.py --html --project-update # everything
python run.py --render-html           # re-open HTML dashboard from the last brief
python run.py --reset-state           # reset lookback window to config default
```

---

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your credentials (never committed):

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com |
| `ATLASSIAN_EMAIL` | Your Atlassian account email |
| `JIRA_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens (scope to Jira) |
| `CONFLUENCE_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens (scope to Confluence) |
| `ATLASSIAN_BASE_URL` | `https://yourcompany.atlassian.net` |
| `SLACK_USER_TOKEN` | See Slack setup below |
| `GITHUB_TOKEN` | See GitHub setup below (optional) |

### 3. Configure your vault and channels

Edit `config.yaml`:
- Set `obsidian_vault_path` to your vault location
- List the Slack channels, Confluence spaces, and Jira projects you want monitored

### 4. Set up Google (Gmail + Calendar + Sheets)

Google credentials are stored **outside the repo** at `~/.config/intel-brief/`:

1. Go to https://console.cloud.google.com
2. Create a project → enable **Gmail API**, **Google Calendar API**, and **Google Sheets API**
3. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID** → Desktop app
4. Download the JSON and save it to:
   ```
   ~/.config/intel-brief/google_credentials.json
   ```
5. On first run, a browser window opens for OAuth consent. The token is cached at `~/.config/intel-brief/google_token.json` and refreshed automatically.

> **If you previously authorized without Sheets:** delete your token and re-authorize:
> ```bash
> rm ~/.config/intel-brief/google_token.json && python run.py
> ```

### 5. Set up Slack

1. Go to https://api.slack.com/apps → **Create New App** → From scratch
2. Under **OAuth & Permissions** → **User Token Scopes**, add:
   - `channels:history`, `channels:read`
   - `groups:history`, `groups:read`
   - `users:read`
3. **Install App to Workspace** → copy the **User OAuth Token** (`xoxp-...`) into `.env`

### 6. Set up GitHub (optional)

Fetches PRs awaiting your review and your open PRs.

1. Go to https://github.com/settings/tokens → **Generate new token (classic)**
2. Grant scopes: `repo` (or `public_repo` for public repos only)
3. Add `GITHUB_TOKEN=ghp_...` to `.env`

If `GITHUB_TOKEN` is not set, the GitHub connector is silently skipped.

### 7. Configure the project tracker (optional)

The `--project-update` flag reads a Google Sheet to generate a weekly project status section. Configure in `config.yaml`:

```yaml
google_sheets:
  project_tracker:
    sheet_id: <your-sheet-id>   # from the sheet URL: /spreadsheets/d/<sheet_id>/
    gid: <tab-gid>              # from the URL: ?gid=<gid>
    departments:
      - Data Science
      - Data Engineering
      - Analytics
    exclude_statuses:
      - Done
      - Deprioritized
```

The sheet must have columns containing **department**, **project**, and **status** (case-insensitive) in the header row.

---

## How it works

### Data fetching
- All connectors fetch **in parallel** using `ThreadPoolExecutor`
- On each run, fetches everything since the last run (first run defaults to 24h)
- Last-run state is stored at `~/.config/intel-brief/state.json` (outside the repo)
- If a connector fails, the others still run and the timestamp is not advanced

### Brief generation
- Claude streams the response live to your terminal as it generates
- Brief opens with a 2–3 sentence **executive summary**, followed by structured sections:
  - **Project Pulse** — key developments across active projects
  - **Priorities & Action Items** — ordered by urgency (🔴🟡🟢)
  - **Who Needs a Response** — people waiting on you
  - **This Week's Calendar** — meetings through Friday
- Prior briefs (last 3 days) and your checked-off items feed back into the next brief for continuity

### Output
- Markdown brief written to `<vault>/<output_folder>/YYYYMM/DD HH-MM.md`
- `--project-update` appends a `## Project Status Update` section grouped by department

### HTML dashboard (`--html` / `--render-html`)
Runs a local HTTP server and opens the brief in your browser as a live dashboard:

- **Executive summary lede** — 2–3 sentence overview above the detail sections
- **Checkbox sync** — checking a task in the browser writes `- [x]` back to the Obsidian `.md` file in real time; a "Saved to Obsidian" toast confirms each write
- **Urgency color coding** — 🔴🟡🟢 items get color-coded left borders for fast scanning
- **Progress bar** — shows `N / total` tasks complete in the card header
- **7-day sparkline** — small completion trend chart next to the progress bar
- **Next meeting chip** — upcoming calendar event shown in the source strip
- **Collapsible sections** — click any `##` heading to collapse/expand
- **Active sidebar nav** — current section highlights as you scroll
- **Project Status Update** — rendered as a separate card when `--project-update` is used
- **Light/dark mode toggle** — preference persisted in localStorage

The server runs on `localhost:15173` (or the next free port) and stays alive until `Ctrl+C`. The `/ping` endpoint returns the file path and server status for debugging.

---

## Security

- `.env` is gitignored — credentials never touch the repo
- Google OAuth tokens live at `~/.config/intel-brief/` — outside the repo
- All API access is read-only (GitHub token only needs `repo` read scope)
- Slack user token reads only the channels listed in `config.yaml`
- The HTML sync server binds to `127.0.0.1` only — not accessible from the network
