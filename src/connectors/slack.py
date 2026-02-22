import os
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def _find_channel_ids(client: WebClient, target_names: set) -> dict:
    """Paginate conversations_list but stop as soon as all targets are found."""
    found = {}
    cursor = None
    while True:
        resp = client.conversations_list(
            types="public_channel,private_channel",
            limit=200,
            exclude_archived=True,
            cursor=cursor,
        )
        for ch in resp.get("channels", []):
            if ch["name"] in target_names:
                found[ch["name"]] = ch["id"]
                if len(found) == len(target_names):
                    return found
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
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
    client = WebClient(token=os.environ["SLACK_USER_TOKEN"])
    channels = config.get("slack", {}).get("channels", [])
    since_ts = str(since.timestamp())
    updates = []

    try:
        channel_map = _find_channel_ids(client, set(channels))
    except SlackApiError as e:
        print(f"[Slack] Could not fetch channel list: {e}")
        return updates

    users_cache = {}

    for channel_name in channels:
        channel_id = channel_map.get(channel_name)
        if not channel_id:
            print(f"[Slack] Channel not found or inaccessible: #{channel_name}")
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
            print(f"[Slack] Error fetching #{channel_name}: {e}")

    return updates
