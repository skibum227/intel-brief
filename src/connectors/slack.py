import json
import logging
import os
from datetime import datetime
from pathlib import Path

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

log = logging.getLogger("intel_brief")

# Cache persisted between runs to avoid re-fetching channel list and user ID
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


def _get_own_user_id(client: WebClient) -> str:
    """Get the authenticated user's Slack ID, cached to disk."""
    cache = _load_cache()
    if "_own_user_id" in cache:
        return cache["_own_user_id"]
    resp = client.auth_test()
    uid = resp.get("user_id", "")
    cache["_own_user_id"] = uid
    _save_cache(cache)
    return uid


def _fetch_thread_replies(
    client: WebClient, channel_id: str, msg_ts: str,
    users_cache: dict, max_replies: int = 5,
) -> list[dict]:
    """Fetch replies for a single thread, returning up to max_replies."""
    try:
        resp = client.conversations_replies(
            channel=channel_id, ts=msg_ts, limit=max_replies + 1,
        )
        replies = []
        for msg in resp.get("messages", [])[1:]:  # skip parent
            if len(replies) >= max_replies:
                break
            user_id = msg.get("user", "")
            replies.append({
                "author": _get_username(client, user_id, users_cache) if user_id else "unknown",
                "text": msg.get("text", "")[:500],
            })
        return replies
    except SlackApiError as e:
        log.warning(f"[Slack] Error fetching thread replies: {e}")
        return []


def _fetch_mentions(
    client: WebClient, user_id: str, since: datetime,
    users_cache: dict, seen_ts: set, thread_reply_min: int = 3,
) -> list[dict]:
    """Fetch messages mentioning the authenticated user."""
    since_ts = str(since.timestamp())
    updates = []
    try:
        resp = client.search_messages(
            query=f"<@{user_id}>",
            sort="timestamp",
            sort_dir="desc",
            count=20,
        )
        for match in resp.get("messages", {}).get("matches", []):
            ts = match.get("ts", "")
            # Skip messages already captured from monitored channels
            if ts in seen_ts:
                continue
            # Skip messages older than since
            try:
                if float(ts) < float(since_ts):
                    continue
            except (ValueError, TypeError):
                continue

            channel_info = match.get("channel", {})
            channel_id = channel_info.get("id", "") if isinstance(channel_info, dict) else ""
            channel_name = channel_info.get("name", "unknown") if isinstance(channel_info, dict) else "unknown"
            author_id = match.get("user", match.get("username", ""))
            reply_count = match.get("reply_count", 0)

            # If the @mention itself sits inside a thread, fetch the thread context.
            # Use thread_ts when present (mention is a reply); else ts (mention is the parent).
            thread_replies = []
            thread_anchor = match.get("thread_ts") or ts
            if channel_id and (reply_count >= thread_reply_min or match.get("thread_ts")):
                thread_replies = _fetch_thread_replies(
                    client, channel_id, thread_anchor, users_cache,
                )

            updates.append({
                "source": "slack",
                "channel": f"@mention (#{channel_name})",
                "author": _get_username(client, author_id, users_cache) if author_id else "unknown",
                "text": match.get("text", ""),
                "timestamp": datetime.fromtimestamp(float(ts)).isoformat() if ts else "",
                "thread_reply_count": reply_count,
                "thread_replies": thread_replies,
            })
    except SlackApiError as e:
        log.warning(f"[Slack] Error fetching mentions: {e}")
    return updates


def _fetch_dms(
    client: WebClient, since: datetime,
    users_cache: dict, seen_ts: set, max_conversations: int = 20,
    thread_reply_min: int = 3,
) -> list[dict]:
    """Fetch recent DM messages."""
    since_ts = str(since.timestamp())
    updates = []
    try:
        # List recent DM conversations
        resp = client.conversations_list(
            types="im,mpim",
            limit=max_conversations,
            exclude_archived=True,
        )
        for conv in resp.get("channels", []):
            conv_id = conv.get("id", "")
            # For IMs, resolve the other user's name
            dm_user = conv.get("user", "")
            try:
                history = client.conversations_history(
                    channel=conv_id, oldest=since_ts, limit=20,
                )
            except SlackApiError:
                continue

            messages = history.get("messages", [])
            if not messages:
                continue

            dm_label = f"DM: {_get_username(client, dm_user, users_cache)}" if dm_user else "DM: group"

            for msg in messages:
                if msg.get("type") != "message" or msg.get("subtype"):
                    continue
                ts = msg.get("ts", "")
                if ts in seen_ts:
                    continue
                user_id = msg.get("user", "")
                reply_count = msg.get("reply_count", 0)

                thread_replies = []
                if reply_count >= thread_reply_min:
                    thread_replies = _fetch_thread_replies(
                        client, conv_id, ts, users_cache,
                    )

                updates.append({
                    "source": "slack",
                    "channel": dm_label,
                    "author": _get_username(client, user_id, users_cache) if user_id else "unknown",
                    "text": msg.get("text", ""),
                    "timestamp": datetime.fromtimestamp(float(ts)).isoformat() if ts else "",
                    "thread_reply_count": reply_count,
                    "thread_replies": thread_replies,
                })
    except SlackApiError as e:
        log.warning(f"[Slack] Error fetching DMs: {e}")
    return updates


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    client = WebClient(
        token=os.environ["SLACK_USER_TOKEN"],
        retry_handlers=[RateLimitErrorRetryHandler(max_retry_count=5)],
    )
    slack_cfg = config.get("slack", {})
    channels = slack_cfg.get("channels", [])
    thread_reply_min = slack_cfg.get("thread_reply_min", 3)
    include_mentions = slack_cfg.get("include_mentions", False)
    include_dms = slack_cfg.get("include_dms", False)
    since_ts = str(since.timestamp())
    updates = []

    try:
        channel_map = _find_channel_ids(client, set(channels))
    except SlackApiError as e:
        log.warning(f"[Slack] Could not fetch channel list: {e}")
        return updates

    users_cache = {}
    seen_ts = set()  # Track message timestamps for deduplication

    # ── Channel messages ─────────────────────────────────────────────────
    for channel_name in channels:
        channel_id = channel_map.get(channel_name)
        if not channel_id:
            log.warning(f"[Slack] #{channel_name} not found — removing from cache")
            cache = _load_cache()
            cache.pop(channel_name, None)
            _save_cache(cache)
            continue

        try:
            response = client.conversations_history(
                channel=channel_id, oldest=since_ts, limit=200,
            )
            for msg in response.get("messages", []):
                if msg.get("type") != "message" or msg.get("subtype"):
                    continue
                ts = msg.get("ts", "")
                seen_ts.add(ts)
                user_id = msg.get("user", "")
                reply_count = msg.get("reply_count", 0)

                # Fetch thread replies for active threads
                thread_replies = []
                if reply_count >= thread_reply_min:
                    thread_replies = _fetch_thread_replies(
                        client, channel_id, ts, users_cache,
                    )

                updates.append({
                    "source": "slack",
                    "channel": f"#{channel_name}",
                    "author": _get_username(client, user_id, users_cache) if user_id else "unknown",
                    "text": msg.get("text", ""),
                    "timestamp": datetime.fromtimestamp(float(ts)).isoformat() if ts else "",
                    "thread_reply_count": reply_count,
                    "thread_replies": thread_replies,
                })
        except SlackApiError as e:
            log.warning(f"[Slack] Error fetching #{channel_name}: {e}")

    # ── @Mentions ────────────────────────────────────────────────────────
    if include_mentions:
        try:
            own_id = _get_own_user_id(client)
            if own_id:
                mention_updates = _fetch_mentions(
                    client, own_id, since, users_cache, seen_ts,
                    thread_reply_min=thread_reply_min,
                )
                updates.extend(mention_updates)
        except Exception as e:
            log.warning(f"[Slack] Error in mentions fetch: {e}")

    # ── DMs ──────────────────────────────────────────────────────────────
    if include_dms:
        try:
            dm_updates = _fetch_dms(
                client, since, users_cache, seen_ts,
                thread_reply_min=thread_reply_min,
            )
            updates.extend(dm_updates)
        except Exception as e:
            log.warning(f"[Slack] Error in DM fetch: {e}")

    return updates
