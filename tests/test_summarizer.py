"""
Tests for src.summarizer.

Anthropic client is mocked — no real API calls. We assert that the rendered
prompts include today's date, the weekday, the lookback hours, and the
name/date discipline language. These guard the recent prompting changes.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src import summarizer


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [MagicMock(text=text)]


def _patch_anthropic():
    """Return a (mock_client_class, mock_messages_create) pair."""
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _FakeMessage("ok")
    return patch.object(summarizer.anthropic, "Anthropic", return_value=fake_client), fake_client


def _today_strs():
    now = datetime.now(timezone.utc).astimezone()
    return now.strftime("%Y-%m-%d"), now.strftime("%A")


# ── summarize() ──────────────────────────────────────────────────────────────

def test_summarize_injects_today_date_and_weekday():
    p, fake = _patch_anthropic()
    today, weekday = _today_strs()
    with p:
        summarizer.summarize(
            all_updates={"slack": []},
            lookback_hours=24.0,
            config={},
        )
    kwargs = fake.messages.create.call_args.kwargs
    sys_prompt = kwargs["system"]
    assert today in sys_prompt
    assert weekday in sys_prompt
    assert "TODAY is" in sys_prompt


def test_summarize_includes_name_discipline():
    p, fake = _patch_anthropic()
    with p:
        summarizer.summarize({"slack": []}, 24.0, {})
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    assert "NAME ACCURACY" in sys_prompt
    assert "exact name as it appears in the source data" in sys_prompt
    assert "do NOT expand" in sys_prompt or "do not invent" in sys_prompt.lower()


def test_summarize_includes_date_discipline():
    p, fake = _patch_anthropic()
    with p:
        summarizer.summarize({"slack": []}, 24.0, {})
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    assert "DATE ACCURACY" in sys_prompt
    assert "Never invent due dates" in sys_prompt or "do not invent" in sys_prompt.lower()


def test_summarize_lookback_hours_rendered():
    p, fake = _patch_anthropic()
    with p:
        summarizer.summarize({"slack": []}, 17.5, {})
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    # Rounded to 1 decimal place
    assert "17.5" in sys_prompt


def test_summarize_no_unfilled_braces():
    """Catch any new {placeholder} that wasn't supplied to .format()."""
    p, fake = _patch_anthropic()
    with p:
        summarizer.summarize({"slack": []}, 24.0, {})
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    user_msg = fake.messages.create.call_args.kwargs["messages"][0]["content"]
    # No literal "{...}" placeholders left in either prompt.
    import re
    assert not re.search(r"\{[a-z_]+\}", sys_prompt), \
        f"Unfilled placeholder in system prompt: {sys_prompt}"
    assert not re.search(r"\{[a-z_]+\}", user_msg), \
        f"Unfilled placeholder in user prompt: {user_msg}"


# ── generate_meeting_prep() ──────────────────────────────────────────────────

def test_meeting_prep_injects_today():
    p, fake = _patch_anthropic()
    today, weekday = _today_strs()
    with p:
        summarizer.generate_meeting_prep(meetings=[], all_updates={}, config={})
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    assert today in sys_prompt
    assert weekday in sys_prompt
    assert "NAME ACCURACY" in sys_prompt
    assert "DATE/TIME ACCURACY" in sys_prompt


def test_meeting_prep_no_unfilled_braces():
    p, fake = _patch_anthropic()
    with p:
        summarizer.generate_meeting_prep([], {}, {})
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    import re
    assert not re.search(r"\{[a-z_]+\}", sys_prompt)


# ── generate_project_update() ────────────────────────────────────────────────

def test_project_update_injects_today():
    p, fake = _patch_anthropic()
    today, weekday = _today_strs()
    with p:
        summarizer.generate_project_update(
            projects=[], weekly_updates={}, prior_context="", config={}
        )
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    assert today in sys_prompt
    assert weekday in sys_prompt
    assert "NAME ACCURACY" in sys_prompt
    assert "DATE ACCURACY" in sys_prompt


def test_project_update_no_unfilled_braces():
    p, fake = _patch_anthropic()
    with p:
        summarizer.generate_project_update([], {}, "", {})
    sys_prompt = fake.messages.create.call_args.kwargs["system"]
    import re
    assert not re.search(r"\{[a-z_]+\}", sys_prompt)
