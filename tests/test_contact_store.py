from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from flowpilot.contact_store import ContactNotFound, ContactStore, DuplicateContact
from flowpilot.ingest import ingest_document
from flowpilot.message_queue import InMemoryQueue
from flowpilot.models import Contact, ContactStatus

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=ZoneInfo("Asia/Colombo"))


def make(name="Nimal", phone="+94771234567"):
    return Contact(name=name, phone=phone)


def test_add_and_get(store):
    c = make()
    store.add(c)
    assert store.get(c.id) == c


def test_unknown_id(store):
    with pytest.raises(ContactNotFound):
        store.get("nope")


def test_database_refuses_duplicate_phone(store):
    store.add(make("Nimal"))
    with pytest.raises(DuplicateContact):
        store.add(make("Someone Else", phone="+94771234567"))


def test_save_updates_status_and_history(store):
    c = make()
    store.add(c)
    c.transition_to(ContactStatus.SCHEDULED, NOW)
    store.save(c)
    loaded = store.get(c.id)
    assert loaded.status is ContactStatus.SCHEDULED
    assert len(loaded.remarks) == 1


def test_save_unknown_contact(store):
    with pytest.raises(ContactNotFound):
        store.save(make())


def test_list_and_filter_by_status(store):
    a, b = make("A", "+94770000001"), make("B", "+94770000002")
    store.add(a)
    store.add(b)
    b.transition_to(ContactStatus.SCHEDULED, NOW)
    store.save(b)
    assert [c.name for c in store.list()] == ["A", "B"]
    assert [c.name for c in store.list(ContactStatus.NEW)] == ["A"]
    assert [c.name for c in store.list(ContactStatus.SCHEDULED)] == ["B"]


def test_survives_restart(cfg):
    s1 = ContactStore(cfg.contacts_store)
    c = make()
    s1.add(c)
    s1.close()
    s2 = ContactStore(cfg.contacts_store)
    assert s2.get(c.id).name == "Nimal"
    s2.close()


def test_two_processes_see_each_others_changes(cfg):
    scheduler_side, admin_side = ContactStore(cfg.contacts_store), ContactStore(cfg.contacts_store)
    c = make()
    scheduler_side.add(c)
    c.transition_to(ContactStatus.SCHEDULED, NOW)
    scheduler_side.save(c)
    assert admin_side.get(c.id).status is ContactStatus.SCHEDULED
    scheduler_side.close()
    admin_side.close()


# ---------- ingest uses the store to avoid calling people twice ----------

def test_same_document_twice_is_not_queued_twice(store):
    q = InMemoryQueue()
    first = ingest_document(SAMPLES / "contacts.pdf", q, store)
    second = ingest_document(SAMPLES / "contacts.pdf", q, store)
    assert len(first.queued) == 3
    assert second.queued == []
    assert len(second.skipped) == 3 and "already known" in second.skipped[0]
    assert q.pending_count() == 3


def test_do_not_call_contact_in_new_document_is_not_called(store):
    blocked = Contact(name="Ruwan Bandara", phone="+94764567890")
    store.add(blocked)
    blocked.transition_to(ContactStatus.SCHEDULED, NOW)
    blocked.transition_to(ContactStatus.DO_NOT_CALL, NOW, remark="Asked not to be called")
    store.save(blocked)

    q = InMemoryQueue()
    report = ingest_document(SAMPLES / "contacts.pdf", q, store)   # contains Ruwan again
    assert "Ruwan Bandara" not in [c.name for c in report.queued]
    assert any("DO_NOT_CALL" in s for s in report.skipped)
