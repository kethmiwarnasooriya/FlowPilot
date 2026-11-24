import re
from datetime import timedelta
from pathlib import Path

from flowpilot.calendar_client import FakeCalendarClient
from flowpilot.calendar_sync import event_id_for, load_state, sync_once
from flowpilot.ingest import ingest_document
from flowpilot.message_queue import SQLiteQueue
from flowpilot.schedule_file import read_entries
from flowpilot.scheduler import run_scheduler

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def schedule_samples(cfg, at, doc="contacts.pdf"):
    q = SQLiteQueue(cfg.queue_db)
    ingest_document(SAMPLES / doc, q)
    run_scheduler(q, cfg, now=at(2026, 11, 24, 10, 7))
    q.close()


def test_creates_one_event_per_entry(cfg, at):
    schedule_samples(cfg, at)
    cal = FakeCalendarClient()
    report = sync_once(cfg, cal)

    assert len(report.created) == 3 and report.error is None
    events = sorted(cal.events.values(), key=lambda e: e.start)
    first = events[0]
    assert first.summary == "Call: Ruwan Bandara (Colombo Digital)"
    assert first.start == at(2026, 11, 24, 10, 15)
    assert first.end - first.start == timedelta(minutes=15)
    assert "Phone: +94764567890" in first.description
    assert "Contact ID:" in first.description


def test_contact_without_email_has_no_email_line(cfg, at):
    schedule_samples(cfg, at)
    cal = FakeCalendarClient()
    sync_once(cfg, cal)
    tharindu = next(e for e in cal.events.values() if "Tharindu" in e.summary)
    assert "Email:" not in tharindu.description


def test_second_run_creates_nothing_new(cfg, at):
    schedule_samples(cfg, at)
    cal = FakeCalendarClient()
    sync_once(cfg, cal)
    report = sync_once(cfg, cal)
    assert report.created == [] and len(cal.events) == 3


def test_new_entries_picked_up_on_next_round(cfg, at):
    schedule_samples(cfg, at)
    cal = FakeCalendarClient()
    sync_once(cfg, cal)
    schedule_samples(cfg, at, doc="contacts.docx")    # scheduler adds more lines
    report = sync_once(cfg, cal)
    assert len(report.created) == 3 and len(cal.events) == 6


def test_network_failure_then_retry(cfg, at):
    schedule_samples(cfg, at)
    flaky = FakeCalendarClient(fail_after=1)          # dies after the first event
    report = sync_once(cfg, flaky)
    assert len(report.created) == 1 and report.error
    assert len(load_state(cfg.sync_state_file)) == 1  # only the successful one recorded

    flaky._fail_after = None                          # network is back
    report = sync_once(cfg, flaky)
    assert len(report.created) == 2 and len(flaky.events) == 3


def test_lost_state_file_does_not_duplicate_events(cfg, at):
    schedule_samples(cfg, at)
    cal = FakeCalendarClient()
    sync_once(cfg, cal)
    cfg.sync_state_file.unlink()                      # state file lost
    report = sync_once(cfg, cal)
    assert len(report.already_existed) == 3
    assert len(cal.events) == 3                       # still no duplicates


def test_event_ids_are_valid_for_google(cfg, at):
    schedule_samples(cfg, at)
    for entry in read_entries(cfg.schedule_file):
        assert re.fullmatch(r"[a-v0-9]{5,1024}", event_id_for(entry))
