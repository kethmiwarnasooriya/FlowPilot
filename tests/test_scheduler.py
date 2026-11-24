from pathlib import Path

import pytest

from flowpilot.ingest import ingest_document
from flowpilot.message_queue import SQLiteQueue
from flowpilot.models import ContactStatus
from flowpilot.schedule_file import ScheduleEntry, append_entry, read_entries
from flowpilot.scheduler import run_scheduler

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def q(cfg):
    queue = SQLiteQueue(cfg.queue_db)
    yield queue
    queue.close()


def test_contacts_scheduled_every_15_minutes(cfg, store, q, at):
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    report = run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 7))

    times = [e.start for e in read_entries(cfg.schedule_file)]
    assert times == [at(2026, 11, 24, 10, 15), at(2026, 11, 24, 10, 30), at(2026, 11, 24, 10, 45)]
    assert [e.name for e in report.scheduled] == ["Ruwan Bandara", "Sanduni Wickramasinghe", "Tharindu Rajapaksha"]
    assert q.pending_count() == 0


def test_store_is_updated_with_status_and_time(cfg, store, q, at):
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 7))

    ruwan = store.list()[0]
    assert ruwan.status is ContactStatus.SCHEDULED
    assert ruwan.next_call_at == at(2026, 11, 24, 10, 15)
    assert "Call scheduled for 2026-11-24 10:15" in ruwan.remarks[-1].text


def test_slots_roll_over_to_next_working_day(cfg, store, q, at):
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    run_scheduler(q, store, cfg, now=at(2026, 11, 27, 16, 20))  # Friday afternoon

    times = [e.start for e in read_entries(cfg.schedule_file)]
    assert times == [at(2026, 11, 27, 16, 30), at(2026, 11, 27, 16, 45), at(2026, 11, 30, 9, 0)]


def test_second_run_continues_after_existing_slots(cfg, store, q, at):
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 7))
    ingest_document(SAMPLES / "contacts.docx", q, store)
    run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 8))

    times = [e.start for e in read_entries(cfg.schedule_file)]
    assert times[3] == at(2026, 11, 24, 11, 0)   # right after the 10:45 slot
    assert len(times) == len(set(times)) == 6     # no double-booked slot


def test_crash_between_write_and_ack_does_not_duplicate(cfg, store, q, at):
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    # Simulate: scheduler wrote the first entry, then crashed before saving the store and acking.
    msg = q.get()
    contact = store.get(msg.body["contact_id"])
    append_entry(cfg.schedule_file, ScheduleEntry(
        entry_id=msg.body["message_uid"], type="call", contact_id=contact.id,
        name=contact.name, company="", phone=contact.phone, email="",
        start=at(2026, 11, 24, 10, 15), duration_minutes=15, created_at=at(2026, 11, 24, 10, 7),
    ))

    report = run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 9))  # restart
    assert report.duplicates == 1
    assert len(read_entries(cfg.schedule_file)) == 3
    # The store caught up with what the file says.
    repaired = store.get(contact.id)
    assert repaired.status is ContactStatus.SCHEDULED
    assert repaired.next_call_at == at(2026, 11, 24, 10, 15)


def test_broken_message_is_rejected_not_retried_forever(cfg, store, q, at):
    q.put({"type": "something_else"})
    q.put({"type": "new_contact", "message_uid": "x", "contact_id": "doesnotexist"})
    report = run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 7))
    assert len(report.rejected) == 2
    assert q.pending_count() == 0 and q.get() is None


def test_damaged_line_is_skipped(cfg, store, q, at):
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 7))
    with open(cfg.schedule_file, "a") as f:
        f.write('{"entry_id": "half-writ')   # crash in the middle of a write
    assert len(read_entries(cfg.schedule_file)) == 3
