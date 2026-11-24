from pathlib import Path

import pytest

from flowpilot.ingest import NEW_CONTACT, ingest_document
from flowpilot.message_queue import InMemoryQueue, SQLiteQueue

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture(params=["sqlite", "memory"])
def queue(request, tmp_path):
    """Run every test against BOTH implementations - they must behave the same."""
    if request.param == "sqlite":
        q = SQLiteQueue(tmp_path / "q.db")
        yield q
        q.close()
    else:
        yield InMemoryQueue()


def test_fifo_order(queue):
    for n in (1, 2, 3):
        queue.put({"n": n})
    got = []
    while (msg := queue.get()) is not None:
        got.append(msg.body["n"])
        queue.ack(msg.id)
    assert got == [1, 2, 3]


def test_empty_queue_returns_none(queue):
    assert queue.get() is None


def test_get_hides_message_until_acked(queue):
    queue.put({"n": 1})
    msg = queue.get()
    assert queue.get() is None          # claimed, so no one else gets it
    assert queue.pending_count() == 0
    queue.ack(msg.id)
    assert queue.recover() == 0         # acked = gone for good


def test_release_puts_message_back_at_front(queue):
    queue.put({"n": 1})
    queue.put({"n": 2})
    msg = queue.get()
    queue.release(msg.id)               # e.g. scheduling failed
    assert queue.get().body == {"n": 1}


def test_recover_after_crash(queue):
    queue.put({"n": 1})
    queue.get()                         # consumer crashes before ack
    assert queue.recover() == 1
    assert queue.get().body == {"n": 1}


def test_sqlite_queue_survives_restart(tmp_path):
    db = tmp_path / "q.db"
    q1 = SQLiteQueue(db)
    q1.put({"n": 1})
    q1.close()                          # "program exits"
    q2 = SQLiteQueue(db)                # "program starts again"
    assert q2.get().body == {"n": 1}
    q2.close()


def test_two_consumers_never_get_the_same_message(tmp_path):
    db = tmp_path / "q.db"
    producer, c1, c2 = SQLiteQueue(db), SQLiteQueue(db), SQLiteQueue(db)
    producer.put({"n": 1})
    producer.put({"n": 2})
    a, b = c1.get(), c2.get()
    assert {a.body["n"], b.body["n"]} == {1, 2}
    assert c1.get() is None
    for q in (producer, c1, c2):
        q.close()


# ---------- ingest: document -> queue ----------

def test_ingest_puts_contacts_in_queue(queue, store):
    result = ingest_document(SAMPLES / "contacts.pdf", queue, store)
    assert queue.pending_count() == len(result.queued) == 3
    msg = queue.get()
    assert msg.body["type"] == NEW_CONTACT
    assert msg.body["source"] == "contacts.pdf"
    # The message only carries the id; the contact itself lives in the store.
    assert store.get(msg.body["contact_id"]).name == "Ruwan Bandara"


def test_ingest_non_contact_document_queues_nothing(queue, store):
    result = ingest_document(SAMPLES / "meeting_notes.docx", queue, store)
    assert not result.is_contact_document
    assert queue.pending_count() == 0
