"""Calendar clients. The sync logic only depends on the CalendarClient interface,
so it can be tested with FakeCalendarClient and run for real with GoogleCalendarClient.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

# Narrowest permission that lets us create and delete events.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    summary: str
    description: str
    start: datetime
    end: datetime
    reminder_minutes: int = 5


class EventAlreadyExists(Exception):
    """The calendar already has an event with this id."""


class CalendarClient(Protocol):
    def create_event(self, event: CalendarEvent) -> str: ...
    def delete_event(self, event_id: str) -> None: ...


class GoogleCalendarClient:
    def __init__(self, credentials_file: Path, token_file: Path, calendar_id: str = "primary"):
        from googleapiclient.discovery import build  # imported here so tests don't need it

        creds = _load_credentials(credentials_file, token_file)
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self._calendar_id = calendar_id

    def create_event(self, event: CalendarEvent) -> str:
        from googleapiclient.errors import HttpError

        body = {
            "id": event.event_id,
            "summary": event.summary,
            "description": event.description,
            "start": {"dateTime": event.start.isoformat()},
            "end": {"dateTime": event.end.isoformat()},
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": event.reminder_minutes}],
            },
        }
        try:
            created = self._service.events().insert(calendarId=self._calendar_id, body=body).execute()
        except HttpError as exc:
            if exc.resp.status == 409:
                raise EventAlreadyExists(event.event_id) from exc
            raise
        return created["id"]

    def delete_event(self, event_id: str) -> None:
        from googleapiclient.errors import HttpError

        try:
            self._service.events().delete(calendarId=self._calendar_id, eventId=event_id).execute()
        except HttpError as exc:
            if exc.resp.status not in (404, 410):  # already gone is fine
                raise


def _load_credentials(credentials_file: Path, token_file: Path):
    """Use the saved token; refresh it if expired; otherwise sign in via the browser once."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not credentials_file.exists():
            raise FileNotFoundError(
                f"{credentials_file.name} not found. Download the OAuth client file from "
                "Google Cloud Console and save it in the project folder (see README)."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
        creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json())
    return creds


class FakeCalendarClient:
    """In-memory calendar for tests. Behaves like Google for duplicate ids."""

    def __init__(self, fail_after: int | None = None):
        self.events: dict[str, CalendarEvent] = {}
        self._fail_after = fail_after  # simulate the network dying after N calls
        self._calls = 0

    def create_event(self, event: CalendarEvent) -> str:
        self._calls += 1
        if self._fail_after is not None and self._calls > self._fail_after:
            raise ConnectionError("simulated network failure")
        if event.event_id in self.events:
            raise EventAlreadyExists(event.event_id)
        self.events[event.event_id] = event
        return event.event_id

    def delete_event(self, event_id: str) -> None:
        self.events.pop(event_id, None)
