# intel-brief

Fetches updates from Slack, Jira, Confluence, Google Calendar, and Gmail, then writes an AI-summarized brief directly into your Obsidian vault.

```bash
python run.py                  # daily brief
python run.py --project-update # daily brief + weekly project status section
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

### 3. Configure your vault and channels

Edit `config.yaml`:
- Set `obsidian_vault_path` to your vault location
- List the Slack channels, Confluence spaces, and Jira projects you want monitored

### 4. Set up Google (Gmail + Calendar + Sheets)

Google credentials are stored **outside the repo** at `~/.config/intel-brief/`:

1. Go to https://console.cloud.google.com
2. Create a project → enable **Gmail API**, **Google Calendar API**, and **Google Sheets API**
3. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID** → Desktop app
4. Download the JSON file and save it to:
   ```
   ~/.config/intel-brief/google_credentials.json
   ```
5. On first run, a browser window will open for OAuth consent. After approval, the token is cached at `~/.config/intel-brief/google_token.json` and refreshed automatically.

> **If you previously set up Gmail/Calendar only:** the Sheets scope was added. Delete your existing token and re-authorize:
> ```bash
> rm ~/.config/intel-brief/google_token.json
> python run.py
> ```

### 5. Set up Slack

1. Go to https://api.slack.com/apps → **Create New App** → From scratch
2. Under **OAuth & Permissions** → **User Token Scopes**, add:
   - `channels:history`, `channels:read`
   - `groups:history`, `groups:read`
   - `users:read`
3. **Install App to Workspace** → copy the **User OAuth Token** (`xoxp-...`) into `.env`

### 6. Configure the project tracker (optional)

The `--project-update` flag reads a Google Sheet to generate a weekly project status section. Configure it in `config.yaml`:

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

The sheet must have columns containing the words **department**, **project**, and **status** (case-insensitive) in the header row.

---

## How it works

- On each run, fetches everything since the last run (first run defaults to 24h)
- Last-run state is tracked at `~/.config/intel-brief/state.json` (outside the repo)
- If a connector fails, the others still run and the timestamp is not advanced
- Output is written to `<vault>/<output_folder>/YYYYMM/DD HH-MM.md`
- `--project-update` fetches 7 days of signals and your project tracker sheet, then appends a `## Project Status Update` section grouped by department

## Security

- `.env` is gitignored — credentials never touch the repo
- Google OAuth tokens live at `~/.config/intel-brief/` — outside the repo
- All API access is read-only
- Slack user token reads only channels you specify in `config.yaml`
