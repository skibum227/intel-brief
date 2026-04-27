import logging
from datetime import datetime, timezone, timedelta
from auth.google_auth import get_google_credentials
from googleapiclient.discovery import build

log = logging.getLogger("intel_brief")


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    creds = get_google_credentials()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # Mon=0 … Fri=4, Sat=5, Sun=6
    days_to_friday = (4 - weekday) if weekday <= 4 else (4 + 7 - weekday)
    friday_eod = (now + timedelta(days=days_to_friday)).replace(
        hour=23, minute=59, second=59, microsecond=0
    )

    # Look back to start of today (or since, whichever is earlier) for past meeting context
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = min(since, start_of_today).isoformat()
    time_max = friday_eod.isoformat()
    max_results = config.get("google_cal", {}).get("max_results", 20)
    updates = []

    try:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        for event in events_result.get("items", []):
            start = event.get("start", {})
            end = event.get("end", {})
            attendees = [
                a.get("displayName") or a.get("email", "")
                for a in event.get("attendees", [])
                if not a.get("self")
            ]
            updates.append({
                "source": "google_cal",
                "title": event.get("summary", "(No title)"),
                "start": start.get("dateTime") or start.get("date", ""),
                "end": end.get("dateTime") or end.get("date", ""),
                "attendees": attendees,
                "location": event.get("location", ""),
                "description": (event.get("description") or "")[:500],
                "organizer": (
                    event.get("organizer", {}).get("displayName")
                    or event.get("organizer", {}).get("email", "")
                ),
            })

    except Exception as e:
        log.warning(f"[Calendar] Error: {e}")

    return updates
