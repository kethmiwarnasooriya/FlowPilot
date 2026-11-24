"""Ingestion step: document -> text -> contacts -> queue."""

from __future__ import annotations

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
            "type": NEW_CONTACT,
            "source": Path(path).name,
            "contact": contact.to_dict(),
        })
    return result
