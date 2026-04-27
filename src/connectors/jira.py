import logging
import os
from datetime import datetime
from atlassian import Jira

from src.config import get_limit

log = logging.getLogger("intel_brief")


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    jira = Jira(
        url=os.environ["ATLASSIAN_BASE_URL"],
        username=os.environ["ATLASSIAN_EMAIL"],
        password=os.environ["JIRA_API_TOKEN"],
        cloud=True,
    )

    projects = config.get("jira", {}).get("projects", [])
    since_str = since.strftime("%Y-%m-%d %H:%M")
    project_list = ", ".join(f'"{p}"' for p in projects)
    jql = f'project in ({project_list}) AND updated >= "{since_str}" ORDER BY updated DESC'
    comment_depth = get_limit(config, "jira_comment_depth")
    updates = []

    try:
        results = jira.jql(
            jql,
            limit=100,
            fields="summary,status,assignee,reporter,comment,priority,updated,labels",
        )

        for issue in results.get("issues", []):
            fields = issue.get("fields", {})
            assignee = fields.get("assignee")
            assignee_name = assignee.get("displayName", "Unassigned") if assignee else "Unassigned"

            comments = fields.get("comment", {}).get("comments", [])
            recent_comments = [
                {
                    "author": c.get("author", {}).get("displayName", ""),
                    "body": c.get("body", "")[:500],
                    "updated": c.get("updated", c.get("created", "")),
                }
                for c in comments[-comment_depth:]
            ]

            updates.append({
                "source": "jira",
                "key": issue.get("key"),
                "summary": fields.get("summary", ""),
                "status": fields.get("status", {}).get("name", ""),
                "priority": fields.get("priority", {}).get("name", ""),
                "assignee": assignee_name,
                "reporter": fields.get("reporter", {}).get("displayName", ""),
                "updated": fields.get("updated", ""),
                "labels": fields.get("labels", []),
                "url": f"{os.environ['ATLASSIAN_BASE_URL'].rstrip('/')}/browse/{issue.get('key')}",
                "recent_comments": recent_comments,
            })

    except Exception as e:
        raise RuntimeError(f"Jira fetch failed: {e}") from e

    return updates
