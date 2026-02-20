from datetime import datetime, timezone, timedelta
from auth.google_auth import get_google_credentials
from googleapiclient.discovery import build


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    creds = get_google_credentials()
    service = build("calendar", "v3", credentials=creds)

    # Calendar is forward-looking: show events from now through next 24 hours
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(hours=24)).isoformat()
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
        print(f"[Calendar] Error: {e}")

    return updates
