import json
import os
import time
import random
from collections import defaultdict
from datetime import datetime, timezone

import anthropic

from src.config import get_limit, log

SYSTEM_PROMPT = """You are a chief of staff and thought partner for JD (Jonathan), the Head of Data at a fintech startup.
You support him across data science, data engineering, and strategic analytics teams.

Important: the person you are briefing IS JD (Jonathan). When you encounter "JD" in any updates —
Slack messages, Jira tickets, emails, Confluence pages — that refers to the user themselves,
not a third party. Do not refer to JD in the third person in the brief.

Your job: analyze updates from Slack, Jira, Confluence, Calendar, and Email, then produce a concise,
high-signal brief that helps JD manage his projects and team — not just review what happened, but
think through what to do next.

NAME ACCURACY (critical — readers see these names):
- Use the exact name as it appears in the source data. Do not invent, abbreviate, translate, or
  guess full names from a handle (e.g. do NOT expand "asmith" to "Alex Smith"). If only a handle
  or first name is given, use that verbatim.
- Never assign an action, message, or ticket to someone unless the source data explicitly attributes
  it to them. If attribution is unclear, omit the name rather than guess.
- If the same person appears under multiple identifiers (Slack handle, email, "displayName"), prefer
  the human-readable display name actually present in the data; do not merge identities you are not
  sure refer to the same person.
- "JD" / "Jonathan" / "jdh385" all refer to the user. Never refer to the user in the third person.

DATE ACCURACY (critical — readers act on these dates):
- TODAY is {today_str} ({today_weekday}). Treat this as ground truth for all relative references
  ("today", "yesterday", "this week", "tomorrow"). Compute days-of-week and dates from this anchor;
  do NOT infer the date from training data or filenames.
- The lookback window for raw data is the last {lookback_hours} hours ending now. Anything outside
  that window is context only.
- When a source includes a timestamp, quote dates in `YYYY-MM-DD` form (or weekday + date for
  meetings) using the timestamp from the data. Do not paraphrase a date you cannot see in the data.
- Never invent due dates, deadlines, or "by Friday"-style targets unless they are explicitly in the
  source. If a deadline is implied but not stated, say "no stated deadline."

Key behaviors:
- If JD has written notes (corrections, context, observations), treat them as ground truth. They
  override raw signals and should be reflected explicitly in the relevant sections.
- Surface patterns across sources. A quiet Slack thread + a stalled Jira ticket + an unreplied
  email can all point to the same underlying issue — connect those dots.
- Think about team dynamics, not just tasks. Flag when someone seems blocked, overloaded, or
  has gone quiet on a project. Proactively suggest check-ins.
- Track open loops. If something was raised in a prior brief or in JD's notes and hasn't been
  resolved, keep it visible.
- Be proactive about risk. Don't wait for a project to be late — flag when momentum is slipping.
- Make concrete recommendations. "Consider talking to X about Y" is more useful than "X is working on Y."

Urgency markers:
🔴 Urgent — needs attention today, blocking something, or someone is waiting
🟡 Today — should address today but not blocking
🟢 FYI — good to know, no action needed soon

Be concise. High signal only — omit anything routine or already resolved.
Bold only names or ticket/project identifiers (e.g. **Alice**, **PROJ-123**).
Do not include a title or date heading — the document template provides that."""

USER_PROMPT = """Analyze the updates below from the past {lookback_hours} hours and produce a brief.

{prior_context_block}{user_notes_block}{resolved_block}{recurring_block}{team_signals_block}{dismissed_block}Open with a 2–3 sentence executive summary (plain paragraph, no heading) naming the day's main theme and single most important action item.

Then format each of the first three sections as a checklist using `- [ ]` for each item.
Omit any section that has nothing meaningful to report.

## Project Pulse
Key developments across active projects. Skip routine status updates.
- [ ] ...

## Priorities & Action Items
What needs to happen today, ordered by urgency. Use urgency markers.
- [ ] 🔴/🟡/🟢 ...

## Who Needs a Response
People waiting on me — who, from where (Slack/email/Jira), and why it matters.
- [ ] **Name** — source, reason

## This Week's Calendar
Meetings through end of Friday. Flag any needing prep or with important context.
(plain text — no checkboxes)

## Market & Regulatory Intel
Only include this section if there is genuinely relevant external news — regulatory actions, competitor moves, or macro shifts that directly affect Perpay's business (BNPL, consumer credit, fintech regulation, direct competitors: Affirm, Afterpay, Klarna). Skip anything routine, speculative, or only tangentially related. 2–4 bullet points max, plain text, no checkboxes. Omit the section entirely if nothing clears the bar.

---

RAW DATA:
{raw_data}"""


def summarize(
    all_updates: dict,
    lookback_hours: float,
    config: dict,
    prior_context: str = "",
    user_notes: str = "",
    completed_items: str = "",
    recurring_items: str = "",
    team_signals: str = "",
    dismissed_items: list[str] | None = None,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    now = datetime.now(timezone.utc).astimezone()
    today_str = now.strftime("%Y-%m-%d")
    today_weekday = now.strftime("%A")

    max_bytes = get_limit(config, "raw_data_max_bytes")
    raw_data = json.dumps(all_updates, indent=2, default=str)
    if len(raw_data) > max_bytes:
        log.warning(f"Raw data truncated from {len(raw_data):,} to {max_bytes:,} chars")
        raw_data = raw_data[:max_bytes] + "\n\n[... truncated due to volume ...]"

    if prior_context:
        prior_context_block = (
            "PRIOR BRIEFS (last few days — use for trend and continuity context only):\n"
            f"{prior_context}\n\n---\n\n"
        )
    else:
        prior_context_block = ""

    if user_notes:
        user_notes_block = (
            "MY NOTES (authoritative corrections and context from prior days — these override raw signals):\n"
            f"{user_notes}\n\n---\n\n"
        )
    else:
        user_notes_block = ""

    if completed_items:
        resolved_block = (
            "RESOLVED (checked off in prior briefs — skip unless there is new development):\n"
            f"{completed_items}\n\n---\n\n"
        )
    else:
        resolved_block = ""

    if recurring_items:
        recurring_block = (
            "RECURRING UNRESOLVED ITEMS (appeared in multiple recent briefs — still unchecked):\n"
            f"{recurring_items}\n\n---\n\n"
        )
    else:
        recurring_block = ""

    if team_signals:
        team_signals_block = (
            "CRITICAL TEAM SIGNALS (only the most serious flags — act on these):\n"
            f"{team_signals}\n\n---\n\n"
        )
    else:
        team_signals_block = ""

    if dismissed_items:
        dismissed_block = (
            "DISMISSED (user marked these as noise — de-prioritize or omit similar items):\n"
            + "\n".join(f"- {fp}" for fp in dismissed_items)
            + "\n\n---\n\n"
        )
    else:
        dismissed_block = ""

    create_kwargs = dict(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT.format(
            today_str=today_str,
            today_weekday=today_weekday,
            lookback_hours=round(lookback_hours, 1),
        ),
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT.format(
                    lookback_hours=round(lookback_hours, 1),
                    prior_context_block=prior_context_block,
                    user_notes_block=user_notes_block,
                    resolved_block=resolved_block,
                    recurring_block=recurring_block,
                    team_signals_block=team_signals_block,
                    dismissed_block=dismissed_block,
                    raw_data=raw_data,
                ),
            }
        ],
    )

    for attempt in range(5):
        try:
            message = client.messages.create(**create_kwargs)
            return message.content[0].text
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503) and attempt < 4:
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning(f"API overloaded — retrying in {wait:.1f}s (attempt {attempt + 1}/5)")
                time.sleep(wait)
            else:
                raise


_MEETING_PREP_SYSTEM = """You are preparing meeting prep notes for JD (Jonathan), the Head of Data at a fintech startup.

TODAY is {today_str} ({today_weekday}). Use this as the anchor for all relative date language
("today", "tomorrow", "later this week"). Do NOT infer the date from anywhere else.

NAME ACCURACY (critical):
- Use the exact attendee names provided in the meeting block. Do not abbreviate, expand, or guess
  full names from email handles. If only an email is provided, use the local part as-is.
- Only attribute Slack/Jira/email activity to an attendee when the source data clearly identifies
  that same person (matching display name or email). When in doubt, omit rather than guess.

DATE/TIME ACCURACY (critical):
- The meeting time provided in each meeting block is authoritative — render it exactly as given,
  including timezone if present. Do not round, shift, or reformat to a different timezone.
- The meeting heading must use the actual scheduled time from the data, not an invented one.

For each upcoming meeting, generate prep notes that help JD walk in prepared. For each meeting:

1. **Meeting context**: What is this meeting likely about? (infer from title, attendees, recent activity)
2. **Attendee context**: For each non-trivial attendee, surface their recent activity:
   - Slack messages or threads they've been active in
   - Jira tickets they're assigned to or have commented on
   - Emails they've sent/received
   - Any relevant Confluence updates
3. **Suggested talking points**: Based on the data, what should JD bring up or be prepared for?
4. **Open items**: Any unresolved threads, blocked tickets, or pending decisions involving these people

Skip meetings that are routine standup/scrum (unless there's specific context worth noting).
Skip attendee context for large meetings (10+ attendees) — just note the meeting purpose.

Output format:

## Meeting Title — HH:MM AM/PM
**Attendees**: Name1, Name2, ...

### Context
Brief description of what this meeting is likely about.

### Attendee Activity
- **Name**: Recent relevant activity from Slack/Jira/email...

### Talking Points
- Suggested topic 1
- Suggested topic 2

Be concise and actionable. Focus on what helps JD prepare, not exhaustive activity logs."""


def generate_meeting_prep(
    meetings: list[dict],
    all_updates: dict,
    config: dict,
) -> str:
    """Generate meeting prep notes by cross-referencing attendees with recent activity."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    now = datetime.now(timezone.utc).astimezone()
    today_str = now.strftime("%Y-%m-%d")
    today_weekday = now.strftime("%A")

    max_bytes = get_limit(config, "raw_data_max_bytes")

    # Build per-meeting blocks with attendee info
    meetings_block = ""
    for event in meetings:
        start = event.get("start", "")
        title = event.get("title", "(No title)")
        attendees = event.get("attendees", [])
        desc = event.get("description", "")
        organizer = event.get("organizer", "")

        meetings_block += f"\n### {title}\n"
        meetings_block += f"- **Time**: {start}\n"
        meetings_block += f"- **Organizer**: {organizer}\n"
        if attendees:
            meetings_block += f"- **Attendees**: {', '.join(attendees)}\n"
        if desc:
            meetings_block += f"- **Description**: {desc[:300]}\n"

    raw_signals = json.dumps(all_updates, indent=2, default=str)
    if len(raw_signals) > max_bytes:
        log.warning(f"Meeting prep signals truncated from {len(raw_signals):,} to {max_bytes:,} chars")
        raw_signals = raw_signals[:max_bytes] + "\n\n[... truncated ...]"

    user_content = (
        f"UPCOMING MEETINGS:\n{meetings_block}\n\n---\n\n"
        f"RECENT ACTIVITY (Slack, Jira, email, Confluence — use to build attendee context):\n{raw_signals}"
    )

    create_kwargs = dict(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=_MEETING_PREP_SYSTEM.format(
            today_str=today_str,
            today_weekday=today_weekday,
        ),
        messages=[{"role": "user", "content": user_content}],
    )

    for attempt in range(5):
        try:
            message = client.messages.create(**create_kwargs)
            return message.content[0].text
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503) and attempt < 4:
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning(f"API overloaded — retrying in {wait:.1f}s (attempt {attempt + 1}/5)")
                time.sleep(wait)
            else:
                raise


_PROJECT_UPDATE_SYSTEM = """You are drafting a Friday project status update for JD's weekly tracker.
JD is the Head of Data at a fintech startup, overseeing Data Science, Data Engineering, and Analytics.

TODAY is {today_str} ({today_weekday}). The reporting window is the 7 days ending today; "this week"
in the output means that window. Do not infer the date from training data or filenames.

NAME ACCURACY (critical):
- Project names: copy them verbatim from the tracker sheet block. Do not rename, abbreviate, or
  consolidate two projects into one even if they sound similar.
- Person names: only attribute work to a person when the source data explicitly says so. Do not
  expand handles into full names or guess owners from a project name.

DATE ACCURACY (critical):
- "Next steps: by [date]" must use a date that appears in the source data, or omit the date.
- Do not invent target dates, sprint endings, or "by EOW" if the source doesn't state one.

PRIMARY SOURCE — use the Confluence project update pages for each team. These contain the actual
week's progress written by team members and are timestamped. Synthesize them into the status summary.

REFERENCE ONLY — the tracker sheet's "Status & Next Steps" column shows last week's recorded status.
Use it only to understand what has changed or progressed this week. Do NOT copy or paraphrase it.

For each project, write a 1-2 sentence status summary reflecting what actually happened this week,
and concrete next steps. If Confluence has no signal for a project, draw from Slack/Jira/email but
make that clear; do not fall back to restating last week's sheet entry.

Output format — return only the markdown below, grouped by department:

## Project Status Update

### Data Science
- **Project Name**: This week's status. Next steps: ...

### Data Engineering
- **Project Name**: This week's status. Next steps: ...

### Analytics
- **Project Name**: This week's status. Next steps: ...

Only include departments that have active projects. Be specific, forward-looking, and concise."""


def generate_project_update(
    projects: list[dict],
    weekly_updates: dict,
    prior_context: str,
    config: dict,
    confluence_pages: list[dict] | None = None,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    now = datetime.now(timezone.utc).astimezone()
    today_str = now.strftime("%Y-%m-%d")
    today_weekday = now.strftime("%A")

    # Sheet data: last week's baseline, grouped by department
    by_dept: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        by_dept[p["department"]].append(p)

    sheet_block = ""
    for dept, items in by_dept.items():
        sheet_block += f"\n### {dept}\n"
        for p in items:
            sheet_block += f"- **{p['project']}**: {p['last_status']}\n"

    # Confluence pages: this week's primary source
    confluence_block = ""
    for page in (confluence_pages or []):
        confluence_block += (
            f"\n### {page['department']} — {page['page_title']}\n"
            f"{page['content']}\n"
        )

    max_bytes = get_limit(config, "project_update_max_bytes")
    raw_signals = json.dumps(weekly_updates, indent=2, default=str)
    if len(raw_signals) > max_bytes:
        log.warning(f"Project update signals truncated from {len(raw_signals):,} to {max_bytes:,} chars")
        raw_signals = raw_signals[:max_bytes] + "\n\n[... truncated ...]"

    prior_block = (
        f"PRIOR BRIEFS (last 7 days — continuity context only):\n{prior_context}\n\n---\n\n"
        if prior_context else ""
    )

    user_content = (
        f"{prior_block}"
        f"LAST WEEK'S TRACKER STATUS (reference only — do not copy):\n{sheet_block}\n\n---\n\n"
        + (
            f"THIS WEEK'S CONFLUENCE PROJECT UPDATES (primary source):\n{confluence_block}\n\n---\n\n"
            if confluence_block else ""
        )
        + f"SUPPLEMENTAL SIGNALS (Slack, Jira, email, calendar — 7 days):\n{raw_signals}"
    )

    create_kwargs = dict(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=_PROJECT_UPDATE_SYSTEM.format(
            today_str=today_str,
            today_weekday=today_weekday,
        ),
        messages=[{"role": "user", "content": user_content}],
    )

    for attempt in range(5):
        try:
            message = client.messages.create(**create_kwargs)
            return message.content[0].text
        except anthropic.APIStatusError as e:
            if e.status_code in (529, 503) and attempt < 4:
                wait = (2 ** attempt) + random.uniform(0, 1)
                log.warning(f"API overloaded — retrying in {wait:.1f}s (attempt {attempt + 1}/5)")
                time.sleep(wait)
            else:
                raise
