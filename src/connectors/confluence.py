import os
import re
import requests
from datetime import datetime, timezone
from requests.auth import HTTPBasicAuth


def _get_cloud_id(base_url: str) -> str:
    resp = requests.get(f"{base_url}/_edge/tenant_info", timeout=10)
    resp.raise_for_status()
    return resp.json()["cloudId"]


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    email = os.environ["ATLASSIAN_EMAIL"]
    base_url = os.environ["ATLASSIAN_BASE_URL"].rstrip("/")

    cloud_id = _get_cloud_id(base_url)
    api_base = f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki"
    auth = HTTPBasicAuth(email, os.environ["CONFLUENCE_API_TOKEN"])

    spaces = config.get("confluence", {}).get("spaces", [])
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
                    clean_body = " ".join(clean_body.split())[:1500]

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

                # If we got a full page and found recent items, keep paginating
                if len(results) < limit:
                    break
                if not found_any_recent:
                    break
                start += limit

        except Exception as e:
            print(f"[Confluence] Error fetching space {space_key}: {e}")

    return updates
