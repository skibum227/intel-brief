import json
import os
import anthropic

SYSTEM_PROMPT = """You are an executive intelligence assistant for the Head of Data at a fintech startup.
You manage briefings across data science, data engineering, and strategic analytics teams.

Your job: analyze updates from Slack, Jira, Confluence, Calendar, and Email, then produce a concise,
high-signal brief. The user is time-constrained. Surface only what matters — skip routine noise.

Urgency markers:
🔴 Urgent — needs attention today, blocking something, or someone is waiting
🟡 Today — should address today but not blocking
🟢 FYI — good to know, no action needed soon

Be direct. Use bullet points. Omit sections that have nothing meaningful to report."""

USER_PROMPT = """Analyze the updates below from the past {lookback_hours} hours and produce a brief.

Include only sections with something meaningful to report:

## Priorities & Action Items
What needs to happen today, ordered by urgency. Use urgency markers.

## Who Needs a Response
People waiting on me — who, from where (Slack/email/Jira), and why it matters.

## Blockers & Decisions
Things stalled or requiring my decision. Include the stakes.

## Project Pulse
Key developments across active projects. Skip routine status updates.

## Today's Calendar
Meetings happening today. Flag any needing prep or with important context.

---

RAW DATA:
{raw_data}"""


def summarize(all_updates: dict, lookback_hours: float) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    raw_data = json.dumps(all_updates, indent=2, default=str)
    if len(raw_data) > 150_000:
        raw_data = raw_data[:150_000] + "\n\n[... truncated due to volume ...]"

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_PROMPT.format(
                    lookback_hours=round(lookback_hours, 1),
                    raw_data=raw_data,
                ),
            }
        ],
    )

    return message.content[0].text
