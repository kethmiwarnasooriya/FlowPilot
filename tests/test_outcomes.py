from datetime import datetime
from pathlib import Path

import pytest

from flowpilot.calendar_client import FakeCalendarClient
from flowpilot.calendar_sync import sync_once
from flowpilot.ingest import ingest_document
from flowpilot.message_queue import SQLiteQueue
from flowpilot.models import ContactStatus, InvalidTransition
from flowpilot.outcomes import (
    add_months,
    parse_delay,
    record_callback,
    record_meeting,
    record_not_interested,
)
from flowpilot.schedule_file import CALLBACK, MEETING, read_entries
from flowpilot.scheduler import run_scheduler

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def q(cfg):
    queue = SQLiteQueue(cfg.queue_db)
    yield queue
    queue.close()


@pytest.fixture
def scheduled(cfg, store, q, at):
    """Three contacts from the PDF, scheduled on Tue 24 Nov from 10:15. Returns them."""
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 7))
    return store.list()


# ---------- parsing "in 2 weeks" ----------

@pytest.mark.parametrize("text, expected", [
    ("3 days", datetime(2026, 11, 27, 10, 0)),
    ("in 2 weeks", datetime(2026, 12, 8, 10, 0)),
    ("a week", datetime(2026, 12, 1, 10, 0)),
    ("1 month", datetime(2026, 12, 24, 10, 0)),
    ("3 Months", datetime(2027, 2, 24, 10, 0)),
])
def test_parse_delay(text, expected):
    assert parse_delay(text, datetime(2026, 11, 24, 10, 0)) == expected


@pytest.mark.parametrize("bad", ["soon", "2 years", "0 days", "two weeks", ""])
def test_parse_delay_rejects_unclear_input(bad):
    with pytest.raises(ValueError):
        parse_delay(bad, datetime(2026, 11, 24))


def test_add_months_clamps_to_end_of_month():
    assert add_months(datetime(2027, 1, 31), 1) == datetime(2027, 2, 28)
    assert add_months(datetime(2028, 1, 31), 1) == datetime(2028, 2, 29)  # leap year
    assert add_months(datetime(2026, 11, 30), 3) == datetime(2027, 2, 28)  # across a year


# ---------- 8a: callback ----------

def test_callback_is_rescheduled_through_the_queue(cfg, store, q, at, scheduled):
    ruwan = scheduled[0]
    contact, not_before = record_callback(
        store, q, ruwan.id, "2 weeks", "Busy with year-end", now=at(2026, 11, 24, 10, 30))
    assert contact.status is ContactStatus.CALLBACK_REQUESTED
    assert not_before == at(2026, 12, 8, 10, 30)
    assert q.pending_count() == 1

    report = run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 31))
    [entry] = report.scheduled
    assert entry.type == CALLBACK
    assert entry.start == at(2026, 12, 8, 10, 30)
    assert "2 weeks" in entry.note and "Busy with year-end" in entry.note

    ruwan = store.get(ruwan.id)
    assert ruwan.status is ContactStatus.SCHEDULED
    assert ruwan.next_call_at == at(2026, 12, 8, 10, 30)
    assert ruwan.call_attempts == 1


def test_callback_landing_on_weekend_moves_to_monday(cfg, store, q, at, scheduled):
    # Tue 24 Nov + 4 days = Sat 28 Nov -> Monday 09:00
    record_callback(store, q, scheduled[0].id, "4 days", "", now=at(2026, 11, 24, 11, 0))
    [entry] = run_scheduler(q, store, cfg, now=at(2026, 11, 24, 11, 1)).scheduled
    assert entry.start == at(2026, 11, 30, 9, 0)


def test_new_contacts_are_not_delayed_by_a_future_callback(cfg, store, q, at, scheduled):
    record_callback(store, q, scheduled[0].id, "2 weeks", "", now=at(2026, 11, 24, 10, 50))
    run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 51))
    report = ingest_document(SAMPLES / "contacts.docx", q, store)
    sched = run_scheduler(q, store, cfg, now=at(2026, 11, 24, 10, 52)).scheduled
    assert [e.start for e in sched] == [
        at(2026, 11, 24, 11, 0), at(2026, 11, 24, 11, 15), at(2026, 11, 24, 11, 30)]
    assert len(report.queued) == 3


def test_bad_delay_changes_nothing(cfg, store, q, at, scheduled):
    with pytest.raises(ValueError):
        record_callback(store, q, scheduled[0].id, "later", "", now=at(2026, 11, 24, 11, 0))
    assert store.get(scheduled[0].id).status is ContactStatus.SCHEDULED
    assert q.pending_count() == 0


# ---------- 8b: not interested / do not call ----------

def test_not_interested(cfg, store, at, scheduled):
    c = record_not_interested(store, scheduled[1].id, "Already has a supplier",
                              now=at(2026, 11, 24, 11, 0))
    assert c.status is ContactStatus.NOT_INTERESTED
    assert c.remarks[-1].text == "Already has a supplier"
    assert store.list(ContactStatus.NOT_INTERESTED) == [c]


def test_do_not_call_blocks_any_future_callback(cfg, store, q, at, scheduled):
    record_not_interested(store, scheduled[1].id, "Asked never to be called",
                          now=at(2026, 11, 24, 11, 0), do_not_call=True)
    with pytest.raises(InvalidTransition):
        record_callback(store, q, scheduled[1].id, "1 week", "", now=at(2026, 11, 24, 11, 5))


def test_remark_is_required(store, at, scheduled):
    with pytest.raises(ValueError):
        record_not_interested(store, scheduled[1].id, "  ", now=at(2026, 11, 24, 11, 0))


# ---------- 8c: interested -> meeting ----------

def test_meeting_goes_into_schedule_and_calendar(cfg, store, at, scheduled):
    tharindu = scheduled[2]
    entry = record_meeting(store, cfg, tharindu.id, at(2026, 12, 2, 14, 0),
                           "Southern Agro office, Galle", "Wants a product demo",
                           now=at(2026, 11, 24, 11, 0))
    assert entry.type == MEETING and entry.duration_minutes == 60
    assert read_entries(cfg.schedule_file)[-1] == entry

    c = store.get(tharindu.id)
    assert c.status is ContactStatus.MEETING_BOOKED
    assert c.meeting_at == at(2026, 12, 2, 14, 0)

    cal = FakeCalendarClient()
    sync_once(cfg, cal)
    meeting = next(e for e in cal.events.values() if e.summary.startswith("Meeting"))
    assert meeting.summary == "Meeting: Tharindu Rajapaksha (Southern Agro)"
    assert meeting.location == "Southern Agro office, Galle"
    assert meeting.reminder_minutes == 60


def test_meeting_time_without_timezone_uses_config_timezone(cfg, store, at, scheduled):
    entry = record_meeting(store, cfg, scheduled[2].id, datetime(2026, 12, 2, 14, 0),
                           "Galle", "", now=at(2026, 11, 24, 11, 0))
    assert entry.start == at(2026, 12, 2, 14, 0)


@pytest.mark.parametrize("when, where", [
    ((2026, 11, 20, 14, 0), "Galle"),   # in the past
    ((2026, 12, 2, 14, 0), "   "),      # no location
])
def test_invalid_meeting_changes_nothing(cfg, store, at, scheduled, when, where):
    with pytest.raises(ValueError):
        record_meeting(store, cfg, scheduled[2].id, at(*when), where, "", now=at(2026, 11, 24, 11, 0))
    assert store.get(scheduled[2].id).status is ContactStatus.SCHEDULED
    assert all(e.type != MEETING for e in read_entries(cfg.schedule_file))


def test_cannot_book_meeting_for_unscheduled_contact(cfg, store, at):
    from flowpilot.models import Contact
    c = Contact(name="Fresh", phone="+94770000009")
    store.add(c)
    with pytest.raises(InvalidTransition):
        record_meeting(store, cfg, c.id, at(2026, 12, 2, 14, 0), "Colombo", "",
                       now=at(2026, 11, 24, 11, 0))
