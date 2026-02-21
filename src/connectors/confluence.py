import os
import re
from datetime import datetime
from atlassian import Confluence


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    confluence = Confluence(
        url=os.environ["ATLASSIAN_BASE_URL"],
        username=os.environ["ATLASSIAN_EMAIL"],
        password=os.environ["CONFLUENCE_API_TOKEN"],
        cloud=True,
    )

    spaces = config.get("confluence", {}).get("spaces", [])
    since_str = since.strftime("%Y-%m-%d %H:%M")
    updates = []

    for space_key in spaces:
        try:
            cql = (
                f'space = "{space_key}" AND lastModified >= "{since_str}" '
                f'ORDER BY lastModified DESC'
            )
            results = confluence.cql(cql, limit=50)

            for result in results.get("results", []):
                page = result.get("content", {})
                page_id = page.get("id")
                if not page_id:
                    continue

                details = confluence.get_page_by_id(
                    page_id,
                    expand="body.view,version",
                )

                body_html = details.get("body", {}).get("view", {}).get("value", "")
                clean_body = re.sub(r"<[^>]+>", " ", body_html)
                clean_body = " ".join(clean_body.split())[:1500]

                updates.append({
                    "source": "confluence",
                    "space": space_key,
                    "title": details.get("title", ""),
                    "author": details.get("version", {}).get("by", {}).get("displayName", ""),
                    "updated_at": details.get("version", {}).get("when", ""),
                    "url": (
                        os.environ["ATLASSIAN_BASE_URL"].rstrip("/")
                        + details.get("_links", {}).get("webui", "")
                    ),
                    "content": clean_body,
                })

        except Exception as e:
            print(f"[Confluence] Error fetching space {space_key}: {e}")

    return updates
