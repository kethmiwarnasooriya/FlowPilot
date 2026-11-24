"""Ingestion step: document -> text -> contacts -> contact store + queue."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from flowpilot.contact_store import ContactStore
from flowpilot.extractor import extract_contacts
from flowpilot.message_queue import MessageQueue
from flowpilot.models import Contact
from flowpilot.reader import read_document

NEW_CONTACT = "new_contact"


@dataclass
class IngestReport:
    queued: list[Contact] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    found_any_contacts: bool = False

    @property
    def is_contact_document(self) -> bool:
        return self.found_any_contacts


def ingest_document(path: str | Path, queue: MessageQueue, store: ContactStore,
                    default_country_code: str = "+94") -> IngestReport:
    """Read a document, save new business contacts and queue them for scheduling.

    Contacts whose phone number is already known are not queued again - this
    also protects people who asked not to be called from being called again.
    """
    extraction = extract_contacts(read_document(path), default_country_code)
    report = IngestReport(skipped=list(extraction.skipped),
                          found_any_contacts=extraction.is_contact_document)

    for contact in extraction.contacts:
        existing = store.find_by_phone(contact.phone)
        if existing:
            report.skipped.append(
                f"{contact.name}: already known as {existing.name} "
                f"(id {existing.id}, status {existing.status.value})"
            )
            continue
        store.add(contact)  # 1. remember the contact ...
        queue.put({         # 2. ... then ask for it to be scheduled
            # Unique id per message, used downstream to detect a message that
            # was delivered twice (e.g. after a crash) and avoid double work.
            "message_uid": uuid.uuid4().hex,
            "type": NEW_CONTACT,
            "source": Path(path).name,
            "contact_id": contact.id,
        })
        report.queued.append(contact)
    return report
