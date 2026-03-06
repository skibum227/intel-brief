from googleapiclient.discovery import build

from auth.google_auth import get_google_credentials


def fetch_projects(config: dict) -> list[dict]:
    """Read active projects from the configured Google Sheet tracker.

    Returns a list of dicts with keys: department, project, last_status.
    Rows with excluded statuses (Done, Deprioritized) are filtered out.
    """
    tracker = config["google_sheets"]["project_tracker"]
    sheet_id = tracker["sheet_id"]
    gid = int(tracker["gid"])
    departments = {d.lower() for d in tracker.get("departments", [])}
    exclude_statuses = {s.lower() for s in tracker.get("exclude_statuses", [])}

    creds = get_google_credentials()
    service = build("sheets", "v4", credentials=creds)
    sheets_api = service.spreadsheets()

    # Resolve tab name from GID
    metadata = sheets_api.get(spreadsheetId=sheet_id).execute()
    tab_name = None
    for sheet in metadata["sheets"]:
        if sheet["properties"]["sheetId"] == gid:
            tab_name = sheet["properties"]["title"]
            break
    if tab_name is None:
        raise ValueError(f"No sheet found with gid={gid} in spreadsheet {sheet_id}")

    result = sheets_api.values().get(spreadsheetId=sheet_id, range=tab_name).execute()
    rows = result.get("values", [])
    if not rows:
        return []

    # Find column indices (case-insensitive substring match)
    header = [h.strip().lower() for h in rows[0]]

    def find_col(keyword: str) -> int:
        for i, h in enumerate(header):
            if keyword in h:
                return i
        return -1

    dept_col = find_col("department")
    project_col = find_col("project")
    status_col = find_col("status")

    if any(c == -1 for c in (dept_col, project_col, status_col)):
        raise ValueError(
            f"Could not find required columns in sheet header: {rows[0]}\n"
            "Expected columns containing: 'department', 'project', 'status'"
        )

    projects = []
    for row in rows[1:]:
        dept = row[dept_col].strip() if dept_col < len(row) else ""
        project = row[project_col].strip() if project_col < len(row) else ""
        status = row[status_col].strip() if status_col < len(row) else ""

        if not dept or not project:
            continue
        if departments and dept.lower() not in departments:
            continue
        if status.lower() in exclude_statuses:
            continue

        projects.append({"department": dept, "project": project, "last_status": status})

    return projects
