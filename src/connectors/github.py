"""GitHub connector — fetches open PRs awaiting your review and your own open PRs."""
import logging
import os
from datetime import datetime, timezone

import requests

from src.config import get_limit

log = logging.getLogger("intel_brief")


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Filter to PRs updated since last run
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    results = []
    body_chars = get_limit(config, "github_pr_body_chars")
    include_body = config.get("github", {}).get("include_pr_body", True)

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
                repository_url = item.get("repository_url", "")
                repo = repository_url.rsplit("/", 1)[-1]
                entry = {
                    "type": pr_type,
                    "title": item["title"],
                    "url": item["html_url"],
                    "repo": repo,
                    "author": item["user"]["login"],
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                    "number": item["number"],
                }

                if include_body:
                    entry["body"] = (item.get("body") or "")[:body_chars]

                    # Fetch review comments
                    # repository_url looks like https://api.github.com/repos/Owner/Repo
                    parts = repository_url.rstrip("/").split("/")
                    if len(parts) >= 2:
                        owner, repo_name = parts[-2], parts[-1]
                        entry["recent_reviews"] = _fetch_reviews(
                            headers, owner, repo_name, item["number"]
                        )
                    else:
                        entry["recent_reviews"] = []

                results.append(entry)
        except Exception as e:
            log.warning(f"[GitHub] Search failed ({pr_type}): {e}")

    repos = config.get("github", {}).get("repos", [])
    repo_filter = " ".join(f"repo:{r}" for r in repos) if repos else ""

    _search(f"is:pr is:open review-requested:@me updated:>={since_str} {repo_filter}".strip(), "review_requested")
    _search(f"is:pr is:open author:@me updated:>={since_str} {repo_filter}".strip(), "your_pr")

    return results


def _fetch_reviews(headers: dict, owner: str, repo: str, pr_number: int) -> list[dict]:
    """Fetch the last 3 reviews for a PR. Returns [] on failure."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        reviews = resp.json()[-3:]
        return [
            {
                "reviewer": r.get("user", {}).get("login", "unknown"),
                "body": (r.get("body") or "")[:300],
            }
            for r in reviews
        ]
    except Exception as e:
        log.warning(f"[GitHub] Failed to fetch reviews for {owner}/{repo}#{pr_number}: {e}")
        return []
