"""Call outcomes recorded by the admin after each call.

  record_callback        - "call me again in 3 days / 2 weeks / 1 month"
  record_not_interested  - not interested, or asked never to be called again
  record_meeting         - interested: book a physical meeting
"""

from __future__ import annotations

import calendar
import re
import uuid
from datetime import datetime, timedelta

from flowpilot.config import Config
from flowpilot.contact_store import ContactStore
from flowpilot.message_queue import MessageQueue
from flowpilot.models import Contact, ContactStatus
from flowpilot.schedule_file import MEETING, ScheduleEntry, append_entry
from flowpilot.scheduler import CALLBACK_REQUEST

_DELAY_RE = re.compile(r"^(?:in\s+)?(\d+|a|an|one)\s+(day|week|month)s?$", re.IGNORECASE)


# ---------- "in 2 weeks" -> a date ----------

def add_months(t: datetime, months: int) -> datetime:
    """Add calendar months. If the day doesn't exist (31 Jan + 1 month), use the
    last day of that month (28/29 Feb) - the same rule banks and calendars use."""
    month_index = t.month - 1 + months
    year, month = t.year + month_index // 12, month_index % 12 + 1
    day = min(t.day, calendar.monthrange(year, month)[1])
    return t.replace(year=year, month=month, day=day)


def parse_delay(text: str, now: datetime) -> datetime:
    """'3 days', 'in 2 weeks', 'a month' -> the datetime that far after `now`."""
    match = _DELAY_RE.match(text.strip())
    if not match:
        raise ValueError(
            f"Can't understand {text!r}. Use e.g. '3 days', '2 weeks' or '1 month'."
        )
    amount_text, unit = match.groups()
    amount = 1 if amount_text.lower() in ("a", "an", "one") else int(amount_text)
    if amount <= 0:
        raise ValueError("The delay must be at least 1")
    unit = unit.lower()
    if unit == "day":
        return now + timedelta(days=amount)
    if unit == "week":
        return now + timedelta(weeks=amount)
    return add_months(now, amount)


# ---------- the three outcomes ----------

def record_callback(store: ContactStore, queue: MessageQueue, contact_id: str,
                    delay: str, remark: str, now: datetime) -> tuple[Contact, datetime]:
    """Contact asked to be called again later: put a callback request in the queue.
    The scheduler will pick the first free slot on or after that date."""
    contact = store.get(contact_id)
    not_before = parse_delay(delay, now)  # validate input before changing anything
    note = f"Asked to call back in {delay.strip()}" + (f": {remark}" if remark else "")
    contact.transition_to(ContactStatus.CALLBACK_REQUESTED, now, remark=note)
    contact.next_call_at = None
    store.save(contact)
    queue.put({
        "message_uid": uuid.uuid4().hex,
        "type": CALLBACK_REQUEST,
        "contact_id": contact.id,
        "not_before": not_before.isoformat(),
        "note": note,
    })
    return contact, not_before


def record_not_interested(store: ContactStore, contact_id: str, remark: str,
                          now: datetime, do_not_call: bool = False) -> Contact:
    """Mark the contact so they are never scheduled again, with the reason."""
    if not remark.strip():
        raise ValueError("Please add a remark explaining why")
    contact = store.get(contact_id)
    status = ContactStatus.DO_NOT_CALL if do_not_call else ContactStatus.NOT_INTERESTED
    contact.transition_to(status, now, remark=remark.strip())
    contact.next_call_at = None
    store.save(contact)
    return contact


def record_meeting(store: ContactStore, cfg: Config, contact_id: str, meeting_at: datetime,
                   location: str, remark: str, now: datetime) -> ScheduleEntry:
    """Interested: book the physical meeting the admin agreed with the contact.
    The meeting goes into the schedule file, so the sync process adds it to the calendar."""
    if not location.strip():
        raise ValueError("A physical meeting needs a location")
    if meeting_at.tzinfo is None:
        meeting_at = meeting_at.replace(tzinfo=cfg.timezone)
    if meeting_at <= now:
        raise ValueError("The meeting time must be in the future")

    contact = store.get(contact_id)
    note = f"Meeting at {location.strip()} on {meeting_at:%Y-%m-%d %H:%M}" + (
        f": {remark}" if remark else "")
    contact.transition_to(ContactStatus.MEETING_BOOKED, now, remark=note)  # validate first
    contact.meeting_at = meeting_at
    contact.next_call_at = None

    entry = ScheduleEntry(
        entry_id=uuid.uuid4().hex, type=MEETING, contact_id=contact.id, name=contact.name,
        company=contact.company, phone=contact.phone, email=contact.email,
        start=meeting_at, duration_minutes=cfg.meeting_duration_minutes, created_at=now,
        location=location.strip(), note=remark,
    )
    append_entry(cfg.schedule_file, entry)  # 1. into the schedule (-> calendar)
    store.save(contact)                     # 2. record the new status
    return entry
