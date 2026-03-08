"""GitHub connector — fetches open PRs awaiting your review and your own open PRs."""
import os
from datetime import datetime, timezone

import requests


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    results = []

    def _search(query: str, pr_type: str):
        try:
            resp = requests.get(
                "https://api.github.com/search/issues",
                headers=headers,
                params={"q": query, "per_page": 25, "sort": "updated"},
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json().get("items", []):
                repo = item.get("repository_url", "").rsplit("/", 1)[-1]
                results.append({
                    "type": pr_type,
                    "title": item["title"],
                    "url": item["html_url"],
                    "repo": repo,
                    "author": item["user"]["login"],
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                    "number": item["number"],
                })
        except Exception:
            pass

    repos = config.get("github", {}).get("repos", [])
    repo_filter = " ".join(f"repo:{r}" for r in repos) if repos else ""

    _search(f"is:pr is:open review-requested:@me {repo_filter}".strip(), "review_requested")
    _search(f"is:pr is:open author:@me {repo_filter}".strip(), "your_pr")

    return results
