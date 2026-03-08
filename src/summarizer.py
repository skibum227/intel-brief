import json
import os
import sys
from collections import defaultdict

import anthropic

SYSTEM_PROMPT = """You are a chief of staff and thought partner for JD (Jonathan), the Head of Data at a fintech startup.
You support him across data science, data engineering, and strategic analytics teams.

Important: the person you are briefing IS JD (Jonathan). When you encounter "JD" in any updates —
Slack messages, Jira tickets, emails, Confluence pages — that refers to the user themselves,
not a third party. Do not refer to JD in the third person in the brief.

Your job: analyze updates from Slack, Jira, Confluence, Calendar, and Email, then produce a concise,
high-signal brief that helps JD manage his projects and team — not just review what happened, but
think through what to do next.

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

{prior_context_block}{user_notes_block}{resolved_block}Open with a 2–3 sentence executive summary (plain paragraph, no heading) naming the day's main theme and single most important action item.

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

---

RAW DATA:
{raw_data}"""


def summarize(
    all_updates: dict,
    lookback_hours: float,
    prior_context: str = "",
    user_notes: str = "",
    completed_items: str = "",
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    raw_data = json.dumps(all_updates, indent=2, default=str)
    if len(raw_data) > 150_000:
        raw_data = raw_data[:150_000] + "\n\n[... truncated due to volume ...]"

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

    print("\n")
    full_text = ""
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT.format(
                    lookback_hours=round(lookback_hours, 1),
                    prior_context_block=prior_context_block,
                    user_notes_block=user_notes_block,
                    resolved_block=resolved_block,
                    raw_data=raw_data,
                ),
            }
        ],
    ) as stream:
        for text in stream.text_stream:
            sys.stdout.write(text)
            sys.stdout.flush()
            full_text += text
    print("\n")
    return full_text


_PROJECT_UPDATE_SYSTEM = """You are drafting a Friday project status update for JD's weekly tracker.
JD is the Head of Data at a fintech startup, overseeing Data Science, Data Engineering, and Analytics.

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
    confluence_pages: list[dict] | None = None,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

    raw_signals = json.dumps(weekly_updates, indent=2, default=str)
    if len(raw_signals) > 100_000:
        raw_signals = raw_signals[:100_000] + "\n\n[... truncated ...]"

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

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=_PROJECT_UPDATE_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )

    return message.content[0].text
