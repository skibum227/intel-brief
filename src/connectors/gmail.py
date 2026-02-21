from datetime import datetime
from auth.google_auth import get_google_credentials
from googleapiclient.discovery import build


def fetch_updates(config: dict, since: datetime) -> list[dict]:
    creds = get_google_credentials()
    service = build("gmail", "v1", credentials=creds)

    max_results = config.get("gmail", {}).get("max_results", 50)
    since_epoch = int(since.timestamp())
    # Exclude newsletters, social, and promotions
    query = f"after:{since_epoch} -category:promotions -category:social"
    updates = []

    try:
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        def handle_message(request_id, response, exception):
            if exception or not response:
                return
            headers = {
                h["name"]: h["value"]
                for h in response.get("payload", {}).get("headers", [])
            }
            updates.append({
                "source": "gmail",
                "subject": headers.get("Subject", "(No subject)"),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "date": headers.get("Date", ""),
                "snippet": response.get("snippet", "")[:300],
            })

        batch = service.new_batch_http_request(callback=handle_message)
        for msg_ref in result.get("messages", []):
            batch.add(
                service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date", "To"],
                )
            )
        batch.execute()

    except Exception as e:
        print(f"[Gmail] Error: {e}")

    return updates
