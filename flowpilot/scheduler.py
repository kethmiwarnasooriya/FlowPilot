"""Scheduler: pops messages from the queue one by one and writes call slots to the schedule file."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from flowpilot.config import Config
from flowpilot.contact_store import ContactNotFound, ContactStore
from flowpilot.ingest import NEW_CONTACT
from flowpilot.message_queue import MessageQueue
from flowpilot.models import Contact, ContactStatus, InvalidTransition
from flowpilot.schedule_file import ScheduleEntry, append_entry, last_call_slot, read_entries
from flowpilot.slots import next_slot


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
    last_slot = last_call_slot(existing)

    while (msg := queue.get()) is not None:
        body = msg.body
        try:
            if body.get("type") != NEW_CONTACT:
                raise ValueError(f"unknown message type {body.get('type')!r}")
            uid = body["message_uid"]
            contact = store.get(body["contact_id"])

            if uid in entries_by_id:
                # Written to the file before a crash. Don't schedule twice, but make
                # sure the store also knows about it (the crash may have happened
                # before the store was updated).
                if contact.status is ContactStatus.NEW:
                    _mark_scheduled(contact, entries_by_id[uid].start, now)
                    store.save(contact)
                report.duplicates += 1
                queue.ack(msg.id)
                continue

            slot = next_slot(now, last_slot, cfg)
            _mark_scheduled(contact, slot, now)  # validates the status change first

            entry = ScheduleEntry(
                entry_id=uid, type="call", contact_id=contact.id, name=contact.name,
                company=contact.company, phone=contact.phone, email=contact.email,
                start=slot, duration_minutes=cfg.call_duration_minutes, created_at=now,
            )
            append_entry(cfg.schedule_file, entry)   # 1. write the schedule line
            store.save(contact)                       # 2. record the new status
            queue.ack(msg.id)                         # 3. only now remove the message

            entries_by_id[uid] = entry
            last_slot = slot
            report.scheduled.append(entry)
        except (KeyError, ValueError, InvalidTransition, ContactNotFound) as exc:
            # A broken message would fail forever if we put it back, so it is
            # removed and reported instead (a "dead letter").
            report.rejected.append(f"message {msg.id}: {type(exc).__name__}: {exc}")
            queue.ack(msg.id)
    return report
