"""Ingestion step: document -> text -> contacts -> queue."""

from __future__ import annotations

import uuid
from pathlib import Path

from flowpilot.extractor import ExtractionResult, extract_contacts
from flowpilot.message_queue import MessageQueue
from flowpilot.reader import read_document

NEW_CONTACT = "new_contact"


def ingest_document(path: str | Path, queue: MessageQueue,
                    default_country_code: str = "+94") -> ExtractionResult:
    """Read a document and put every business contact found into the queue.

    Documents that contain no business contacts put nothing in the queue.
    """
    text = read_document(path)
    result = extract_contacts(text, default_country_code)
    for contact in result.contacts:
        queue.put({
            # Unique id per message, used downstream to detect a message that
            # was delivered twice (e.g. after a crash) and avoid double work.
            "message_uid": uuid.uuid4().hex,
            "type": NEW_CONTACT,
            "source": Path(path).name,
            "contact": contact.to_dict(),
        })
    return result
