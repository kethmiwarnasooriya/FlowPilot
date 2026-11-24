"""Scheduler: pops messages from the queue one by one and writes call slots to the schedule file.

Message types it understands:
  new_contact - first call to a contact from a document      (contact must be NEW)
  callback    - contact asked to be called again later       (contact must be CALLBACK_REQUESTED)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from flowpilot.config import Config
from flowpilot.contact_store import ContactNotFound, ContactStore
from flowpilot.message_queue import MessageQueue
from flowpilot.models import Contact, ContactStatus, InvalidTransition
from flowpilot.schedule_file import (
    CALL, CALLBACK, ScheduleEntry, append_entry, read_entries, taken_call_slots,
)
from flowpilot.slots import next_free_slot

NEW_CONTACT = "new_contact"
CALLBACK_REQUEST = "callback"

# message type -> (status the contact must be in, entry type written to the file)
MESSAGE_RULES = {
    NEW_CONTACT: (ContactStatus.NEW, CALL),
    CALLBACK_REQUEST: (ContactStatus.CALLBACK_REQUESTED, CALLBACK),
}


@dataclass
class SchedulerReport:
    scheduled: list[ScheduleEntry] = field(default_factory=list)
    duplicates: int = 0
    rejected: list[str] = field(default_factory=list)


def _mark_scheduled(contact: Contact, slot: datetime, now: datetime) -> None:
    contact.transition_to(ContactStatus.SCHEDULED, now,
                          remark=f"Call scheduled for {slot:%Y-%m-%d %H:%M}")
    contact.next_call_at = slot


def run_scheduler(queue: MessageQueue, store: ContactStore, cfg: Config,
                  now: datetime | None = None) -> SchedulerReport:
    """Process every pending message, then return. `now` can be fixed for testing."""
    now = now or datetime.now(cfg.timezone)
    report = SchedulerReport()

    queue.recover()  # messages left "in progress" by a previous crash go back in line

    existing = read_entries(cfg.schedule_file)
    entries_by_id = {e.entry_id: e for e in existing}
    taken = taken_call_slots(existing)

    while (msg := queue.get()) is not None:
        body = msg.body
        try:
            msg_type = body.get("type")
            if msg_type not in MESSAGE_RULES:
                raise ValueError(f"unknown message type {msg_type!r}")
            required_status, entry_type = MESSAGE_RULES[msg_type]
            uid = body["message_uid"]
            contact = store.get(body["contact_id"])

            if uid in entries_by_id:
                # Written to the file before a crash. Don't schedule twice, but make
                # sure the store also knows about it (the crash may have happened
                # before the store was updated).
                if contact.status is required_status:
                    _mark_scheduled(contact, entries_by_id[uid].start, now)
                    store.save(contact)
                report.duplicates += 1
                queue.ack(msg.id)
                continue

            if contact.status is not required_status:
                raise InvalidTransition(
                    f"{msg_type} for {contact.name} ignored: status is {contact.status.value}"
                )

            earliest = now
            if body.get("not_before"):
                earliest = max(now, datetime.fromisoformat(body["not_before"]))
            slot = next_free_slot(earliest, taken, cfg)
            _mark_scheduled(contact, slot, now)

            entry = ScheduleEntry(
                entry_id=uid, type=entry_type, contact_id=contact.id, name=contact.name,
                company=contact.company, phone=contact.phone, email=contact.email,
                start=slot, duration_minutes=cfg.call_duration_minutes, created_at=now,
                note=body.get("note", ""),
            )
            append_entry(cfg.schedule_file, entry)   # 1. write the schedule line
            store.save(contact)                       # 2. record the new status
            queue.ack(msg.id)                         # 3. only now remove the message

            entries_by_id[uid] = entry
            taken.append(slot)
            report.scheduled.append(entry)
        except (KeyError, ValueError, InvalidTransition, ContactNotFound) as exc:
            # A broken message would fail forever if we put it back, so it is
            # removed and reported instead (a "dead letter").
            report.rejected.append(f"message {msg.id}: {type(exc).__name__}: {exc}")
            queue.ack(msg.id)
    return report
