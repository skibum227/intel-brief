"""
Tests for src.connectors.confluence.

Covers the recent CQL-search refactor + the existing project-tracker drilldown.
All HTTP is mocked with `responses`; conftest blocks raw sockets so any
unmocked call fails the test.
"""
from datetime import datetime, timezone

import pytest
import responses

from src.connectors import confluence

CLOUD_ID = "33877fe5-4f42-4e7a-980d-8aee60ad6b6a"
BASE_URL = "https://example.atlassian.net"
API_BASE = f"https://api.atlassian.com/ex/confluence/{CLOUD_ID}/wiki"


def _register_cloud_id():
    responses.add(
        responses.GET,
        f"{BASE_URL}/_edge/tenant_info",
        json={"cloudId": CLOUD_ID},
        status=200,
    )


# ── _strip_html ──────────────────────────────────────────────────────────────

def test_strip_html_basic():
    out = confluence._strip_html("<p>Hello <b>world</b></p>")
    assert out == "Hello world"


def test_strip_html_skip_first_table():
    html = "<table><tr><td>meta</td></tr></table><p>Body text</p>"
    out = confluence._strip_html(html, skip_first_table=True)
    assert "meta" not in out
    assert "Body text" in out


def test_strip_html_collapses_whitespace():
    html = "<p>line1</p>\n\n   <p>line2</p>"
    assert confluence._strip_html(html) == "line1 line2"


# ── fetch_updates: CQL endpoint ──────────────────────────────────────────────

@responses.activate
def test_fetch_updates_happy_path():
    _register_cloud_id()

    # CQL search returns 1 page
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/search",
        json={
            "results": [
                {"id": "100", "version": {"when": "2026-04-29T12:00:00.000Z"}}
            ]
        },
        status=200,
    )
    # Page detail
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/100",
        json={
            "id": "100",
            "title": "Weekly Update",
            "version": {
                "when": "2026-04-29T12:00:00.000Z",
                "by": {"displayName": "Alice"},
            },
            "body": {"view": {"value": "<p>Hello <b>world</b></p>"}},
            "_links": {"webui": "/spaces/DE/pages/100"},
        },
        status=200,
    )

    config = {"confluence": {"spaces": ["DE"]}}
    since = datetime(2026, 4, 28, tzinfo=timezone.utc)

    out = confluence.fetch_updates(config, since)

    assert len(out) == 1
    row = out[0]
    assert row["space"] == "DE"
    assert row["title"] == "Weekly Update"
    assert row["author"] == "Alice"
    assert row["content"] == "Hello world"
    assert row["url"] == f"{BASE_URL}/spaces/DE/pages/100"

    # Verify the CQL we sent
    search_call = [c for c in responses.calls if "/content/search" in c.request.url][0]
    assert "lastmodified+%3E%3D" in search_call.request.url or "lastmodified%20%3E%3D" in search_call.request.url
    assert "ORDER+BY+lastmodified+DESC" in search_call.request.url or "ORDER%20BY%20lastmodified%20DESC" in search_call.request.url
    assert 'space+%3D+%22DE%22' in search_call.request.url or 'space%20%3D%20%22DE%22' in search_call.request.url


@responses.activate
def test_fetch_updates_400_logged_not_raised(caplog):
    """A 400 from CQL must be logged as a warning and not crash the run."""
    _register_cloud_id()
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/search",
        json={"message": "Bad Request"},
        status=400,
    )

    config = {"confluence": {"spaces": ["DE"]}}
    since = datetime(2026, 4, 28, tzinfo=timezone.utc)

    out = confluence.fetch_updates(config, since)
    assert out == []
    assert any("Error fetching space DE" in r.getMessage() for r in caplog.records)


@responses.activate
def test_fetch_updates_empty_results():
    _register_cloud_id()
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/search",
        json={"results": []},
        status=200,
    )
    config = {"confluence": {"spaces": ["DE"]}}
    since = datetime(2026, 4, 28, tzinfo=timezone.utc)
    assert confluence.fetch_updates(config, since) == []


@responses.activate
def test_fetch_updates_naive_since_is_handled():
    """Passing a tz-naive datetime must not raise — function is contracted to coerce."""
    _register_cloud_id()
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/search",
        json={"results": []},
        status=200,
    )
    config = {"confluence": {"spaces": ["DE"]}}
    naive = datetime(2026, 4, 28)  # no tzinfo
    confluence.fetch_updates(config, naive)


@responses.activate
def test_fetch_updates_pagination_stops_when_short_page():
    _register_cloud_id()
    # First call: full page (50 results)
    page_one = [
        {"id": str(i), "version": {"when": "2026-04-29T12:00:00.000Z"}}
        for i in range(50)
    ]
    # Second call: short page → loop should exit
    page_two = [
        {"id": "999", "version": {"when": "2026-04-29T12:00:00.000Z"}}
    ]
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/search",
        json={"results": page_one},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/search",
        json={"results": page_two},
        status=200,
    )
    # Detail fetches for all 51 ids
    for pid in [str(i) for i in range(50)] + ["999"]:
        responses.add(
            responses.GET,
            f"{API_BASE}/rest/api/content/{pid}",
            json={
                "id": pid,
                "title": f"P{pid}",
                "version": {"when": "2026-04-29T12:00:00.000Z", "by": {"displayName": "X"}},
                "body": {"view": {"value": "<p>x</p>"}},
                "_links": {"webui": f"/p/{pid}"},
            },
            status=200,
        )

    config = {"confluence": {"spaces": ["DE"]}}
    since = datetime(2026, 4, 28, tzinfo=timezone.utc)
    out = confluence.fetch_updates(config, since)
    assert len(out) == 51
    # Two paginated search calls, no third
    search_calls = [c for c in responses.calls if "/content/search" in c.request.url]
    assert len(search_calls) == 2


# ── fetch_team_project_updates: drill-down ───────────────────────────────────

@responses.activate
def test_project_updates_no_spaces_configured_returns_empty():
    out = confluence.fetch_team_project_updates({})
    assert out == []


@responses.activate
def test_project_updates_drilldown_depth_zero():
    _register_cloud_id()
    # 1) find "Project Tracking" parent
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content",
        json={"results": [{"id": "PARENT", "title": "Project Tracking"}]},
        status=200,
    )
    # 2) children of PARENT (depth=0 → pick most recent)
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/PARENT/child/page",
        json={
            "results": [
                {"id": "OLD", "title": "Old", "version": {"when": "2026-01-01T00:00:00Z"}},
                {"id": "NEW", "title": "Recent Update", "version": {"when": "2026-04-29T00:00:00Z"}},
            ]
        },
        status=200,
    )
    # 3) detail for NEW
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/NEW",
        json={
            "id": "NEW",
            "title": "Recent Update",
            "version": {"when": "2026-04-29T00:00:00Z"},
            "body": {"view": {"value": "<p>contents</p>"}},
            "_links": {"webui": "/spaces/DS/pages/NEW"},
        },
        status=200,
    )

    config = {
        "google_sheets": {
            "project_tracker": {
                "confluence_spaces": [
                    {"space": "DS", "department": "Data Science", "nesting_depth": 0}
                ]
            }
        }
    }
    out = confluence.fetch_team_project_updates(config)
    assert len(out) == 1
    assert out[0]["space"] == "DS"
    assert out[0]["page_title"] == "Recent Update"
    assert "contents" in out[0]["content"]


@responses.activate
def test_project_updates_prefers_week_page_over_folder():
    """At depth=0, if the most-recent child looks like a YYYYMM folder,
    we should reach back for a sibling that looks like a weekly update."""
    _register_cloud_id()
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content",
        json={"results": [{"id": "PARENT"}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/PARENT/child/page",
        json={
            "results": [
                # Most recent is a folder
                {"id": "FOLDER", "title": "202604", "version": {"when": "2026-04-30T00:00:00Z"}},
                # Sibling that's a real weekly page
                {"id": "WEEK", "title": "2026-04-20 through 2026-04-24",
                 "version": {"when": "2026-04-25T00:00:00Z"}},
            ]
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/WEEK",
        json={
            "id": "WEEK",
            "title": "2026-04-20 through 2026-04-24",
            "version": {"when": "2026-04-25T00:00:00Z"},
            "body": {"view": {"value": "<p>body</p>"}},
            "_links": {"webui": "/w"},
        },
        status=200,
    )

    config = {
        "google_sheets": {
            "project_tracker": {
                "confluence_spaces": [
                    {"space": "DS", "nesting_depth": 0}
                ]
            }
        }
    }
    out = confluence.fetch_team_project_updates(config)
    assert len(out) == 1
    assert out[0]["page_title"].startswith("2026-04-20")


@responses.activate
def test_project_updates_skip_first_table():
    _register_cloud_id()
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content",
        json={"results": [{"id": "PARENT"}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/PARENT/child/page",
        json={"results": [
            {"id": "P", "title": "Page", "version": {"when": "2026-04-29T00:00:00Z"}}
        ]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content/P",
        json={
            "id": "P",
            "title": "Page",
            "version": {"when": "2026-04-29T00:00:00Z"},
            "body": {"view": {"value": "<table><tr><td>META</td></tr></table><p>real body</p>"}},
            "_links": {"webui": "/p"},
        },
        status=200,
    )

    config = {
        "google_sheets": {
            "project_tracker": {
                "confluence_spaces": [
                    {"space": "DS", "nesting_depth": 0, "skip_first_table": True}
                ]
            }
        }
    }
    out = confluence.fetch_team_project_updates(config)
    assert "META" not in out[0]["content"]
    assert "real body" in out[0]["content"]


@responses.activate
def test_project_updates_missing_parent_logs_and_skips(caplog):
    _register_cloud_id()
    responses.add(
        responses.GET,
        f"{API_BASE}/rest/api/content",
        json={"results": []},
        status=200,
    )
    config = {
        "google_sheets": {
            "project_tracker": {
                "confluence_spaces": [{"space": "MISSING", "nesting_depth": 0}]
            }
        }
    }
    out = confluence.fetch_team_project_updates(config)
    assert out == []
    assert any("No 'Project Tracking' page found in space MISSING" in r.getMessage()
               for r in caplog.records)
