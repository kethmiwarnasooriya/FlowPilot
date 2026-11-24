"""Calendar sync process: reads the schedule file and creates a calendar event per entry.

Runs separately from the scheduler. Usage:
    python -m flowpilot.calendar_sync           # sync once
    python -m flowpilot.calendar_sync --watch   # keep running, check every N seconds
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from flowpilot.calendar_client import CalendarClient, CalendarEvent, EventAlreadyExists
from flowpilot.config import Config, load_config
from flowpilot.schedule_file import CALL, CALLBACK, MEETING, ScheduleEntry, read_entries


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    already_existed: list[str] = field(default_factory=list)
    error: str | None = None


# ---------- sync state: entry_id -> calendar event id ----------

def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, str]) -> None:
    """Write to a temp file, then rename. The rename is atomic, so a crash
    can never leave a half-written state file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------- turning a schedule entry into a calendar event ----------

def event_id_for(entry: ScheduleEntry) -> str:
    # Google event ids may only use a-v and 0-9. Our entry ids are hex (0-9, a-f),
    # and the "fp" prefix is also in a-v, so this is always valid - and always the
    # same for the same entry, which is what makes retries safe.
    return f"fp{entry.entry_id}"


TITLE_PREFIX = {CALL: "Call", CALLBACK: "Follow-up call", MEETING: "Meeting"}


def to_event(entry: ScheduleEntry, reminder_minutes: int) -> CalendarEvent:
    prefix = TITLE_PREFIX.get(entry.type, entry.type.capitalize())
    title = f"{prefix}: {entry.name}" + (f" ({entry.company})" if entry.company else "")
    details = [f"Phone: {entry.phone}"]
    if entry.email:
        details.append(f"Email: {entry.email}")
    if entry.company:
        details.append(f"Company: {entry.company}")
    if entry.note:
        details += ["", f"Note: {entry.note}"]
    details += ["", f"Contact ID: {entry.contact_id}"]
    if entry.type in (CALL, CALLBACK):
        details.append("After the call, record the outcome with this Contact ID.")
    description = "\n".join(details)
    # A physical meeting needs travel time, so it gets an earlier reminder.
    reminder = 60 if entry.type == MEETING else reminder_minutes
    return CalendarEvent(
        event_id=event_id_for(entry),
        summary=title,
        description=description,
        start=entry.start,
        end=entry.start + timedelta(minutes=entry.duration_minutes),
        reminder_minutes=reminder,
        location=entry.location,
    )


# ---------- one sync round ----------

def sync_once(cfg: Config, client: CalendarClient) -> SyncReport:
    report = SyncReport()
    state = load_state(cfg.sync_state_file)

    for entry in read_entries(cfg.schedule_file):
        if entry.entry_id in state:
            continue  # already synced in an earlier round
        event = to_event(entry, cfg.reminder_minutes)
        try:
            state[entry.entry_id] = client.create_event(event)
            report.created.append(entry.entry_id)
        except EventAlreadyExists:
            # Created before, but our state file didn't record it (e.g. crash). Fine.
            state[entry.entry_id] = event.event_id
            report.already_existed.append(entry.entry_id)
        except Exception as exc:
            # Network/API problem: stop this round. Unsynced entries are retried next round.
            report.error = f"{type(exc).__name__}: {exc}"
            break
        finally:
            save_state(cfg.sync_state_file, state)  # save progress after every entry
    return report


def watch(cfg: Config, client: CalendarClient) -> None:
    print(f"Watching {cfg.schedule_file} every {cfg.sync_poll_seconds}s (Ctrl+C to stop)")
    while True:
        report = sync_once(cfg, client)
        if report.created or report.already_existed:
            print(f"Synced {len(report.created)} new event(s)")
        if report.error:
            print(f"Sync error, will retry: {report.error}")
        time.sleep(cfg.sync_poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the call schedule to Google Calendar")
    parser.add_argument("--watch", action="store_true", help="keep running and poll for new entries")
    args = parser.parse_args()

    from flowpilot.calendar_client import GoogleCalendarClient

    cfg = load_config()
    client = GoogleCalendarClient(cfg.credentials_file, cfg.token_file, cfg.calendar_id)
    if args.watch:
        try:
            watch(cfg, client)
        except KeyboardInterrupt:
            print("Stopped.")
    else:
        report = sync_once(cfg, client)
        print(f"Created {len(report.created)} event(s), "
              f"{len(report.already_existed)} already existed.")
        if report.error:
            print(f"Error: {report.error} - run again to retry the rest.")


if __name__ == "__main__":
    main()
