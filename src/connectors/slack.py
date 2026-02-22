import json
import os
from datetime import datetime
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from tqdm import tqdm

# Channel name→ID cache persisted between runs to avoid paginating conversations_list
_CACHE_PATH = Path.home() / ".config" / "intel-brief" / "slack_channel_cache.json"


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text()) if _CACHE_PATH.exists() else {}
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _find_channel_ids(client: WebClient, target_names: set) -> dict:
    """Return {name: id}. Serves from disk cache; only calls API for cache misses."""
    cache = _load_cache()
    found = {n: cache[n] for n in target_names if n in cache}
    missing = target_names - set(found)

    if missing:
        cursor = None
        while missing:
            resp = client.conversations_list(
                types="public_channel,private_channel",
                limit=200,
                exclude_archived=True,
                cursor=cursor,
            )
            for ch in resp.get("channels", []):
                if ch["name"] in missing:
                    found[ch["name"]] = ch["id"]
                    cache[ch["name"]] = ch["id"]
                    missing.discard(ch["name"])
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor or not missing:
                break
        _save_cache(cache)

    return found


def _get_username(client: WebClient, user_id: str, cache: dict) -> str:
    """Look up a single user by ID, cached so each user is only fetched once."""
    if user_id in cache:
        return cache[user_id]
    try:
        resp = client.users_info(user=user_id)
        user = resp.get("user", {})
        name = (
            user.get("profile", {}).get("display_name")
            or user.get("real_name")
            or user_id
        )
    except SlackApiError:
        name = user_id
    cache[user_id] = name
    return name


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    client = WebClient(
        token=os.environ["SLACK_USER_TOKEN"],
        # Auto-waits and retries on 429 rate-limit responses (up to 5 times)
        retry_handlers=[RateLimitErrorRetryHandler(max_retry_count=5)],
    )
    channels = config.get("slack", {}).get("channels", [])
    since_ts = str(since.timestamp())
    updates = []

    try:
        channel_map = _find_channel_ids(client, set(channels))
    except SlackApiError as e:
        tqdm.write(f"[Slack] Could not fetch channel list: {e}")
        return updates

    users_cache = {}

    for channel_name in tqdm(channels, desc="    channels", unit="ch", leave=False, position=1):
        channel_id = channel_map.get(channel_name)
        if not channel_id:
            tqdm.write(f"    [Slack] #{channel_name} not found — removing from cache")
            cache = _load_cache()
            cache.pop(channel_name, None)
            _save_cache(cache)
            continue

        try:
            response = client.conversations_history(
                channel=channel_id,
                oldest=since_ts,
                limit=200,
            )
            for msg in response.get("messages", []):
                if msg.get("type") != "message" or msg.get("subtype"):
                    continue
                user_id = msg.get("user", "")
                updates.append({
                    "source": "slack",
                    "channel": f"#{channel_name}",
                    "author": _get_username(client, user_id, users_cache) if user_id else "unknown",
                    "text": msg.get("text", ""),
                    "timestamp": datetime.fromtimestamp(float(msg["ts"])).isoformat(),
                    "thread_reply_count": msg.get("reply_count", 0),
                })
        except SlackApiError as e:
            tqdm.write(f"    [Slack] Error fetching #{channel_name}: {e}")

    return updates
