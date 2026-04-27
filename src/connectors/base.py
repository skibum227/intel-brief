"""Typed definitions for connector return formats and the Connector protocol.

Documentation-first types for IDE support. No runtime enforcement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypedDict


class SlackUpdate(TypedDict):
    source: str
    channel: str
    author: str
    text: str
    timestamp: str
    thread_reply_count: int


class JiraUpdate(TypedDict):
    source: str
    key: str
    summary: str
    status: str
    priority: str
    assignee: str
    reporter: str
    updated: str
    labels: list[str]
    url: str
    recent_comments: list[str]


class ConfluenceUpdate(TypedDict):
    source: str
    space: str
    title: str
    author: str
    updated_at: str
    url: str
    content: str


class GmailUpdate(TypedDict):
    source: str
    subject: str
    from_addr: str
    to: str
    date: str
    snippet: str


class CalendarUpdate(TypedDict):
    source: str
    title: str
    start: str
    end: str
    attendees: list[str]
    location: str
    description: str
    organizer: str


class GitHubUpdate(TypedDict):
    type: str
    title: str
    url: str
    repo: str
    author: str
    created_at: str
    updated_at: str
    number: int


class NewsUpdate(TypedDict):
    source: str
    title: str
    summary: str
    url: str
    published_at: str
    type: str


class Connector(Protocol):
    def fetch_updates(self, config: dict, since: datetime) -> list[dict]: ...
