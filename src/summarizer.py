import json
import os
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

Be direct. Use bullet points. Omit sections that have nothing meaningful to report.
Do not include a title or date heading — the document template provides that."""

USER_PROMPT = """Analyze the updates below from the past {lookback_hours} hours and produce a brief.

{prior_context_block}{user_notes_block}Include only sections with something meaningful to report:

## Priorities & Action Items
What needs to happen today, ordered by urgency. Use urgency markers.

## Who Needs a Response
People waiting on me — who, from where (Slack/email/Jira), and why it matters.

## Blockers & Decisions
Things stalled or requiring my decision. Include the stakes.

## Project Pulse
Key developments across active projects. Skip routine status updates.

## Team Health
Team members who may need a check-in — blocked, going quiet, overloaded, or waiting on direction.

## Open Loops
Commitments, questions, or items raised in prior briefs or my notes that haven't been resolved yet.

## Risk & Momentum
Projects losing velocity, at risk of slipping, or with unresolved dependencies. Flag early.

## Recommendations
Proactive suggestions based on patterns — what to prioritize, who to talk to, decisions worth making now.

## This Week's Calendar
Meetings through end of Friday. Flag any needing prep or with important context.

---

RAW DATA:
{raw_data}"""


def summarize(all_updates: dict, lookback_hours: float, prior_context: str = "", user_notes: str = "") -> str:
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

    message = client.messages.create(
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
                    raw_data=raw_data,
                ),
            }
        ],
    )

    return message.content[0].text
