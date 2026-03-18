# intel-brief

Fetches updates from Slack, Jira, Confluence, Google Calendar, Gmail, and GitHub, then writes an AI-summarized brief into your Obsidian vault — with an optional live HTML dashboard that syncs checkboxes and notes back to Obsidian.

```bash
python run.py                         # daily brief → Obsidian
python run.py --html                  # brief + live HTML dashboard (opens in browser)
python run.py --project-update        # brief + weekly project status section
python run.py --html --project-update # everything
python run.py --render-html           # re-open HTML dashboard from the last brief
python run.py --reset-state           # reset lookback window to config default
python search.py "query"              # search across all past briefs
python search.py "query" --limit 5   # limit results
python migrate_briefs.py             # preview legacy file migration
python migrate_briefs.py --execute   # apply legacy file migration
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
| `NEWS_API_KEY` | https://newsapi.org — free tier, 100 req/day (optional) |

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

To restrict GitHub to specific repos, add a `github.repos` list to `config.yaml`:


```yaml
github:
  repos:
    - MyOrg/my-repo
    - MyOrg/another-repo
```

If omitted, all repos visible to your token are searched.

### 7. Set up news feeds (optional)

Three sources run automatically — no API key required for two of them:

- **Regulatory RSS** — CFPB, Federal Reserve, OCC, FDIC (always on)
- **SEC EDGAR 8-K filings** — material events from Affirm, Block, PayPal (always on)
- **NewsAPI** — keyword-filtered news; requires `NEWS_API_KEY` in `.env`

Configure in `config.yaml` under `news:`:

```yaml
news:
  enabled: true
  keywords:
    - Affirm
    - Afterpay
    - Klarna
    - BNPL
    - "buy now pay later"
    - "consumer credit"
    - "fintech regulation"
  edgar_tickers:
    - AFRM
    - SQ
    - PYPL
  rss_feeds: []   # add extra RSS feed URLs here if needed
```

Claude filters aggressively — only items directly relevant to Perpay's position appear in the brief. The section is omitted entirely if nothing clears the bar.

### 8. Configure the project tracker (optional)

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
- **Recurring unresolved items** (unchecked across 2+ briefs) are surfaced explicitly so nothing slips through
- **Critical team signals** are injected when there are blocked Jira tickets or team members with 3+ stale high-priority tickets

### Output
- Markdown brief written to `<vault>/<output_folder>/YYYYMM/DD HH-MM.md`
- `--project-update` appends a `## Project Status Update` section grouped by department
- Each brief includes a `## My Notes` section at the bottom — write anything there and it feeds into the next day's brief as authoritative context

### HTML dashboard (`--html` / `--render-html`)
Runs a local HTTP server and opens the brief in your browser as a live dashboard:

- **Executive summary lede** — 2–3 sentence overview above the detail sections
- **Checkbox sync** — checking a task in the browser writes `- [x]` back to the Obsidian `.md` file in real time; a "Saved to Obsidian" toast confirms each write
- **My Notes card** — write notes directly in the dashboard; "Save to Obsidian" (or Cmd/Ctrl+Enter) writes them to the `## My Notes` section of the `.md` file; notes load automatically on page open
- **NEW badges** — action items that didn't appear in yesterday's brief are tagged `NEW` so you can see what's changed at a glance
- **Urgency color coding** — 🔴🟡🟢 items get color-coded left borders for fast scanning
- **Progress bar** — shows `N / total` tasks complete in the card header
- **7-day sparkline** — small completion trend chart next to the progress bar
- **Next meeting chip** — upcoming calendar event shown in the source strip
- **Collapsible sections** — click any `##` heading to collapse/expand
- **Active sidebar nav** — current section highlights as you scroll
- **Project Status Update** — rendered as a separate card when `--project-update` is used
- **Light/dark mode toggle** — preference persisted in localStorage

The server runs on `localhost:15173` (or the next free port) and stays alive until `Ctrl+C`. The `/ping` endpoint returns the file path and server status for debugging.

### Market & Regulatory Intel
A `## Market & Regulatory Intel` section appears at the bottom of each brief when relevant external signals are found:

- **Regulatory RSS** — CFPB, Fed, OCC, FDIC press releases filtered since last run
- **SEC EDGAR** — 8-K filings (material events) for Affirm, Block, and PayPal
- **NewsAPI** — keyword-targeted news for BNPL, competitors, and fintech regulation

Claude only surfaces items that directly affect Perpay's business. The section is omitted entirely on quiet days.

### Search (`search.py`)
Search across all past briefs from the command line:

```bash
python search.py "project name"
python search.py "Alice blocked" --limit 5
```

- Case-insensitive substring search across all brief `.md` files
- Shows up to 3 matching snippets per brief with 1 line of surrounding context, match highlighted in `[brackets]`
- Results sorted newest-first, limited to `--limit` briefs (default 15)
- Prints an **Obsidian deep-link URI** (`obsidian://open?...`) for each result — click to jump directly to that note in Obsidian

### Migrating legacy brief files (`migrate_briefs.py`)

Older versions of intel-brief wrote briefs as `YYYY-MM-DD.md` directly in the `Intel Briefs/` folder. The current format is `YYYYMM/DD HH-MM.md` (date-based subfolders). To migrate:

```bash
python migrate_briefs.py             # preview — shows what would be moved, no changes made
python migrate_briefs.py --execute   # apply — moves files into the new folder structure
```

Legacy files are renamed to `DD 09-00.md` inside the appropriate `YYYYMM/` subfolder (time defaults to 09:00 since the old format had no time component). Files are skipped if the destination already exists.

---

## Security

- `.env` is gitignored — credentials never touch the repo
- Google OAuth tokens live at `~/.config/intel-brief/` — outside the repo
- All API access is read-only (GitHub token only needs `repo` read scope)
- Slack user token reads only the channels listed in `config.yaml`
- The HTML sync server binds to `127.0.0.1` only — not accessible from the network
