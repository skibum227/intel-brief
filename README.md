# intel-brief

Fetches updates from Slack, Jira, Confluence, Google Calendar, and Gmail, then writes an AI-summarized brief directly into your Obsidian vault.

```
python run.py
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
| `ATLASSIAN_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens |
| `ATLASSIAN_BASE_URL` | `https://yourcompany.atlassian.net` |
| `SLACK_USER_TOKEN` | See Slack setup below |

### 3. Configure your vault and channels

Edit `config.yaml`:
- Set `obsidian_vault_path` to your vault location
- List the Slack channels, Confluence spaces, and Jira projects you want monitored

### 4. Set up Google (Gmail + Calendar)

Google credentials are stored **outside the repo** at `~/.config/intel-brief/`:

1. Go to https://console.cloud.google.com
2. Create a project → enable **Gmail API** and **Google Calendar API**
3. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID** → Desktop app
4. Download the JSON file and save it to:
   ```
   ~/.config/intel-brief/google_credentials.json
   ```
5. On first run, a browser window will open for OAuth consent. After approval, the token is cached at `~/.config/intel-brief/google_token.json` and refreshed automatically.

### 5. Set up Slack

1. Go to https://api.slack.com/apps → **Create New App** → From scratch
2. Under **OAuth & Permissions** → **User Token Scopes**, add:
   - `channels:history`, `channels:read`
   - `groups:history`, `groups:read`
   - `users:read`
3. **Install App to Workspace** → copy the **User OAuth Token** (`xoxp-...`) into `.env`

---

## How it works

- On each run, fetches everything since the last run (first run defaults to 24h)
- Last-run state is tracked at `~/.config/intel-brief/state.json` (outside the repo)
- If a connector fails, the others still run and the timestamp is not advanced
- Output is written to `<vault>/<output_folder>/YYYY-MM-DD.md`

## Security

- `.env` is gitignored — credentials never touch the repo
- Google OAuth tokens live at `~/.config/intel-brief/` — outside the repo
- All API access is read-only
- Slack user token reads only channels you specify in `config.yaml`
