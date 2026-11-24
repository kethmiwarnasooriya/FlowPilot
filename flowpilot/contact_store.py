"""Contact store: the single source of truth for every contact and their status.

Backed by SQLite so that several processes (scheduler, admin commands) can
read and update contacts safely, and so the database itself guarantees that
one phone number belongs to only one contact.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flowpilot.models import Contact, ContactStatus


class DuplicateContact(Exception):
    """A contact with this phone number already exists."""


class ContactNotFound(Exception):
    """No contact with this id."""


class ContactStore:
    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS contacts (
                   id     TEXT PRIMARY KEY,
                   phone  TEXT NOT NULL UNIQUE,   -- the database refuses duplicates
                   status TEXT NOT NULL,          -- copied out of data so we can filter on it
                   data   TEXT NOT NULL           -- the full contact as JSON
               )"""
        )

    def add(self, contact: Contact) -> None:
        try:
            self._db.execute(
                "INSERT INTO contacts (id, phone, status, data) VALUES (?, ?, ?, ?)",
                (contact.id, contact.phone, contact.status.value, json.dumps(contact.to_dict())),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateContact(contact.phone) from exc

    def save(self, contact: Contact) -> None:
        """Write back changes to an existing contact."""
        cur = self._db.execute(
            "UPDATE contacts SET phone = ?, status = ?, data = ? WHERE id = ?",
            (contact.phone, contact.status.value, json.dumps(contact.to_dict()), contact.id),
        )
        if cur.rowcount == 0:
            raise ContactNotFound(contact.id)

    def get(self, contact_id: str) -> Contact:
        row = self._db.execute("SELECT data FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        if row is None:
            raise ContactNotFound(contact_id)
        return Contact.from_dict(json.loads(row[0]))

    def find_by_phone(self, phone: str) -> Contact | None:
        row = self._db.execute("SELECT data FROM contacts WHERE phone = ?", (phone,)).fetchone()
        return Contact.from_dict(json.loads(row[0])) if row else None

    def list(self, status: ContactStatus | None = None) -> list[Contact]:
        if status is None:
            rows = self._db.execute("SELECT data FROM contacts ORDER BY rowid").fetchall()
        else:
            rows = self._db.execute(
                "SELECT data FROM contacts WHERE status = ? ORDER BY rowid", (status.value,)
            ).fetchall()
        return [Contact.from_dict(json.loads(r[0])) for r in rows]

    def close(self) -> None:
        self._db.close()
