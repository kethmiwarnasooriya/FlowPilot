from pathlib import Path

from flowpilot.ingest import ingest_document
from flowpilot.message_queue import SQLiteQueue
from flowpilot.schedule_file import ScheduleEntry, append_entry, read_entries
from flowpilot.scheduler import run_scheduler

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_contacts_scheduled_every_15_minutes(cfg, at):
    q = SQLiteQueue(cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q)
    report = run_scheduler(q, cfg, now=at(2026, 11, 24, 10, 7))

    times = [e.start for e in read_entries(cfg.schedule_file)]
    assert times == [at(2026, 11, 24, 10, 15), at(2026, 11, 24, 10, 30), at(2026, 11, 24, 10, 45)]
    assert [e.name for e in report.scheduled] == ["Ruwan Bandara", "Sanduni Wickramasinghe", "Tharindu Rajapaksha"]
    assert q.pending_count() == 0


def test_slots_roll_over_to_next_working_day(cfg, at):
    q = SQLiteQueue(cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q)
    run_scheduler(q, cfg, now=at(2026, 11, 27, 16, 20))  # Friday afternoon

    times = [e.start for e in read_entries(cfg.schedule_file)]
    assert times == [at(2026, 11, 27, 16, 30), at(2026, 11, 27, 16, 45), at(2026, 11, 30, 9, 0)]


def test_second_run_continues_after_existing_slots(cfg, at):
    q = SQLiteQueue(cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q)
    run_scheduler(q, cfg, now=at(2026, 11, 24, 10, 7))
    ingest_document(SAMPLES / "contacts.docx", q)
    run_scheduler(q, cfg, now=at(2026, 11, 24, 10, 8))

    times = [e.start for e in read_entries(cfg.schedule_file)]
    assert times[3] == at(2026, 11, 24, 11, 0)   # right after the 10:45 slot
    assert len(times) == len(set(times)) == 6     # no double-booked slot


def test_crash_between_write_and_ack_does_not_duplicate(cfg, at):
    q = SQLiteQueue(cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q)
    # Simulate: scheduler wrote the first entry, then crashed before ack.
    msg = q.get()
    body = msg.body
    append_entry(cfg.schedule_file, ScheduleEntry(
        entry_id=body["message_uid"], type="call", contact_id=body["contact"]["id"],
        name=body["contact"]["name"], company="", phone=body["contact"]["phone"], email="",
        start=at(2026, 11, 24, 10, 15), duration_minutes=15, created_at=at(2026, 11, 24, 10, 7),
    ))

    report = run_scheduler(q, cfg, now=at(2026, 11, 24, 10, 9))  # restart
    assert report.duplicates == 1
    assert len(read_entries(cfg.schedule_file)) == 3


def test_broken_message_is_rejected_not_retried_forever(cfg, at):
    q = SQLiteQueue(cfg.queue_db)
    q.put({"type": "something_else"})
    report = run_scheduler(q, cfg, now=at(2026, 11, 24, 10, 7))
    assert len(report.rejected) == 1
    assert q.pending_count() == 0 and q.get() is None


def test_damaged_line_is_skipped(cfg, at):
    q = SQLiteQueue(cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q)
    run_scheduler(q, cfg, now=at(2026, 11, 24, 10, 7))
    with open(cfg.schedule_file, "a") as f:
        f.write('{"entry_id": "half-writ')   # crash in the middle of a write
    assert len(read_entries(cfg.schedule_file)) == 3
