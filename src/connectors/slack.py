import os
from datetime import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    client = WebClient(token=os.environ["SLACK_USER_TOKEN"])
    channels = config.get("slack", {}).get("channels", [])
    since_ts = str(since.timestamp())
    updates = []

    # Build user ID -> display name map
    users_map = {}
    try:
        for page in client.users_list():
            for user in page.get("members", []):
                display = (
                    user.get("profile", {}).get("display_name")
                    or user.get("real_name")
                    or user["id"]
                )
                users_map[user["id"]] = display
    except SlackApiError as e:
        print(f"[Slack] Could not fetch user list: {e}")

    # Build channel name -> ID map
    channel_map = {}
    try:
        for page in client.conversations_list(types="public_channel,private_channel"):
            for ch in page.get("channels", []):
                channel_map[ch["name"]] = ch["id"]
    except SlackApiError as e:
        print(f"[Slack] Could not fetch channel list: {e}")
        return updates

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
                updates.append({
                    "source": "slack",
                    "channel": f"#{channel_name}",
                    "author": users_map.get(msg.get("user", ""), msg.get("user", "unknown")),
                    "text": msg.get("text", ""),
                    "timestamp": datetime.fromtimestamp(float(msg["ts"])).isoformat(),
                    "thread_reply_count": msg.get("reply_count", 0),
                })
        except SlackApiError as e:
            print(f"[Slack] Error fetching #{channel_name}: {e}")

    return updates
