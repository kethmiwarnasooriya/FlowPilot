"""Scheduler: pops messages from the queue one by one and writes call slots to the schedule file."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from flowpilot.config import Config
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


def run_scheduler(queue: MessageQueue, cfg: Config, now: datetime | None = None) -> SchedulerReport:
    """Process every pending message, then return. `now` can be fixed for testing."""
    now = now or datetime.now(cfg.timezone)
    report = SchedulerReport()

    queue.recover()  # messages left "in progress" by a previous crash go back in line

    existing = read_entries(cfg.schedule_file)
    known_ids = {e.entry_id for e in existing}
    last_slot = last_call_slot(existing)

    while (msg := queue.get()) is not None:
        body = msg.body
        try:
            if body.get("type") != NEW_CONTACT:
                raise ValueError(f"unknown message type {body.get('type')!r}")
            uid = body["message_uid"]
            if uid in known_ids:
                # Already written before a crash - don't schedule twice.
                report.duplicates += 1
                queue.ack(msg.id)
                continue

            contact = Contact.from_dict(body["contact"])
            slot = next_slot(now, last_slot, cfg)
            contact.transition_to(ContactStatus.SCHEDULED, now, remark=f"Call scheduled for {slot:%Y-%m-%d %H:%M}")
            contact.next_call_at = slot

            entry = ScheduleEntry(
                entry_id=uid, type="call", contact_id=contact.id, name=contact.name,
                company=contact.company, phone=contact.phone, email=contact.email,
                start=slot, duration_minutes=cfg.call_duration_minutes, created_at=now,
            )
            append_entry(cfg.schedule_file, entry)   # 1. write ...
            queue.ack(msg.id)                         # 2. ... then acknowledge

            known_ids.add(uid)
            last_slot = slot
            report.scheduled.append(entry)
        except (KeyError, ValueError, InvalidTransition) as exc:
            # A broken message would fail forever if we put it back, so it is
            # removed and reported instead (a "dead letter").
            report.rejected.append(f"message {msg.id}: {exc}")
            queue.ack(msg.id)
    return report
