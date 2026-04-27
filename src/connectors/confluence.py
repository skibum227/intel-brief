import logging
import os
import re
import requests
from datetime import datetime, timezone
from requests.auth import HTTPBasicAuth

from src.config import get_limit

log = logging.getLogger("intel_brief")


def _get_cloud_id(base_url: str) -> str:
    resp = requests.get(f"{base_url}/_edge/tenant_info", timeout=10)
    resp.raise_for_status()
    return resp.json()["cloudId"]


def _strip_html(html: str, skip_first_table: bool = False) -> str:
    """Strip HTML tags, optionally removing the first table element first."""
    if skip_first_table:
        html = re.sub(r"<table[\s\S]*?</table>", "", html, count=1, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    return " ".join(text.split())


# Pattern matching date-range week titles (e.g., "2026-04-20 through 2026-04-24")
_WEEK_TITLE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\s+(through|to|-)\s+\d{4}-\d{2}-\d{2}", re.IGNORECASE)
# Pattern matching YYYYMM folder names
_FOLDER_TITLE_RE = re.compile(r"^\d{6}$")


def _most_recent_child(api_base: str, auth, parent_id: str, depth: int) -> dict | None:
    """Drill `depth` levels into the child hierarchy, always picking the
    most-recently-modified child at each level. Returns the target page dict
    (with at minimum 'id' and 'title'), or None if any level is empty.

    At the final level (depth=0), prefers pages whose titles look like weekly
    updates over archive folders, to avoid picking a folder that was incidentally
    modified more recently.
    """
    resp = requests.get(
        f"{api_base}/rest/api/content/{parent_id}/child/page",
        auth=auth,
        params={"expand": "version", "limit": 50},
        timeout=30,
    )
    resp.raise_for_status()
    children = resp.json().get("results", [])
    if not children:
        return None

    children.sort(key=lambda p: p.get("version", {}).get("when", ""), reverse=True)

    if depth == 0:
        # At the final level, prefer weekly update pages over archive folders
        # if the most recent child looks like an archive folder
        top = children[0]
        title = top.get("title", "")
        if _FOLDER_TITLE_RE.match(title):
            # Look for a sibling that's an actual weekly page
            for child in children:
                if _WEEK_TITLE_RE.search(child.get("title", "")):
                    return child
        return top

    return _most_recent_child(api_base, auth, children[0]["id"], depth - 1)


def fetch_team_project_updates(config: dict) -> list[dict]:
    """For each team space, find the 'Project Tracking' parent page, drill down
    `nesting_depth` levels to reach the most recent update page, and return its content.

    nesting_depth controls the folder structure:
      0 = pages directly under "Project Tracking"         (e.g. Data Science)
      1 = Project Tracking > {year} > page                (e.g. Data Engineering)
      2 = Project Tracking > {year} > {month} > page      (e.g. Strategic Analytics)

    Returns list of {"space": str, "department": str, "page_title": str,
                      "content": str, "url": str}
    """
    space_configs = (
        config.get("google_sheets", {})
              .get("project_tracker", {})
              .get("confluence_spaces", [])
    )
    if not space_configs:
        return []

    email = os.environ["ATLASSIAN_EMAIL"]
    base_url = os.environ["ATLASSIAN_BASE_URL"].rstrip("/")
    cloud_id = _get_cloud_id(base_url)
    api_base = f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki"
    auth = HTTPBasicAuth(email, os.environ["CONFLUENCE_API_TOKEN"])
    max_chars = get_limit(config, "confluence_project_chars")

    results = []
    for sc in space_configs:
        space_key = sc["space"]
        department = sc.get("department", space_key)
        skip_first_table = sc.get("skip_first_table", False)
        nesting_depth = sc.get("nesting_depth", 0)
        try:
            # Find the "Project Tracking" parent page in this space
            search_resp = requests.get(
                f"{api_base}/rest/api/content",
                auth=auth,
                params={
                    "spaceKey": space_key,
                    "title": "Project Tracking",
                    "type": "page",
                    "expand": "version",
                    "limit": 5,
                },
                timeout=30,
            )
            search_resp.raise_for_status()
            pages = search_resp.json().get("results", [])
            if not pages:
                log.warning(f"[Confluence] No 'Project Tracking' page found in space {space_key}")
                continue

            parent_id = pages[0]["id"]

            # Drill down through intermediate folders to the most recent update page
            target = _most_recent_child(api_base, auth, parent_id, nesting_depth)
            if not target:
                log.warning(f"[Confluence] No pages found under 'Project Tracking' in {space_key}")
                continue

            page_id = target["id"]
            page_title = target.get("title", "")

            # Fetch full page content
            detail_resp = requests.get(
                f"{api_base}/rest/api/content/{page_id}",
                auth=auth,
                params={"expand": "body.view,version"},
                timeout=30,
            )
            detail_resp.raise_for_status()
            details = detail_resp.json()

            body_html = details.get("body", {}).get("view", {}).get("value", "")
            content = _strip_html(body_html, skip_first_table=skip_first_table)
            content = content[:max_chars]

            webui = details.get("_links", {}).get("webui", "")
            results.append({
                "space": space_key,
                "department": department,
                "page_title": page_title,
                "content": content,
                "url": base_url + webui,
            })

        except Exception as e:
            log.warning(f"[Confluence] Error fetching project updates for {space_key}: {e}")

    return results


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    email = os.environ["ATLASSIAN_EMAIL"]
    base_url = os.environ["ATLASSIAN_BASE_URL"].rstrip("/")

    cloud_id = _get_cloud_id(base_url)
    api_base = f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki"
    auth = HTTPBasicAuth(email, os.environ["CONFLUENCE_API_TOKEN"])

    spaces = config.get("confluence", {}).get("spaces", [])
    body_chars = get_limit(config, "confluence_body_chars")
    # Ensure since is timezone-aware for comparison
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    updates = []

    for space_key in spaces:
        try:
            start = 0
            limit = 50
            while True:
                resp = requests.get(
                    f"{api_base}/rest/api/content",
                    auth=auth,
                    params={
                        "spaceKey": space_key,
                        "type": "page",
                        "expand": "version",
                        "limit": limit,
                        "start": start,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    break

                found_any_recent = False
                for page in results:
                    updated_at = page.get("version", {}).get("when", "")
                    if not updated_at:
                        continue
                    page_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    if page_dt < since:
                        continue

                    found_any_recent = True
                    page_id = page.get("id")

                    detail_resp = requests.get(
                        f"{api_base}/rest/api/content/{page_id}",
                        auth=auth,
                        params={"expand": "body.view,version"},
                        timeout=30,
                    )
                    detail_resp.raise_for_status()
                    details = detail_resp.json()

                    body_html = details.get("body", {}).get("view", {}).get("value", "")
                    clean_body = re.sub(r"<[^>]+>", " ", body_html)
                    clean_body = " ".join(clean_body.split())[:body_chars]

                    webui = details.get("_links", {}).get("webui", "")
                    updates.append({
                        "source": "confluence",
                        "space": space_key,
                        "title": details.get("title", ""),
                        "author": details.get("version", {}).get("by", {}).get("displayName", ""),
                        "updated_at": updated_at,
                        "url": base_url + webui,
                        "content": clean_body,
                    })

                if len(results) < limit:
                    break
                if not found_any_recent:
                    break
                start += limit

        except Exception as e:
            log.warning(f"[Confluence] Error fetching space {space_key}: {e}")

    return updates
