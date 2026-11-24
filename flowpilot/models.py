"""Core data model: a business contact and the life cycle of calling them."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ContactStatus(str, Enum):
    NEW = "NEW"                                # extracted from a document, not scheduled yet
    SCHEDULED = "SCHEDULED"                    # has a call time slot
    CALLBACK_REQUESTED = "CALLBACK_REQUESTED"  # asked us to call back later
    NOT_INTERESTED = "NOT_INTERESTED"          # not interested - stop calling
    DO_NOT_CALL = "DO_NOT_CALL"                # explicitly asked never to be called
    MEETING_BOOKED = "MEETING_BOOKED"          # interested - physical meeting arranged


# Which status can move to which. Anything not listed here is rejected.
ALLOWED_TRANSITIONS: dict[ContactStatus, set[ContactStatus]] = {
    ContactStatus.NEW: {ContactStatus.SCHEDULED},
    ContactStatus.SCHEDULED: {
        ContactStatus.SCHEDULED,  # moved to a different slot
        ContactStatus.CALLBACK_REQUESTED,
        ContactStatus.NOT_INTERESTED,
        ContactStatus.DO_NOT_CALL,
        ContactStatus.MEETING_BOOKED,
    },
    ContactStatus.CALLBACK_REQUESTED: {ContactStatus.SCHEDULED},
    ContactStatus.NOT_INTERESTED: set(),   # final
    ContactStatus.DO_NOT_CALL: set(),      # final
    ContactStatus.MEETING_BOOKED: set(),   # final
}

# Outcomes that mean "a call happened", used to count attempts.
CALL_OUTCOMES = {
    ContactStatus.CALLBACK_REQUESTED,
    ContactStatus.NOT_INTERESTED,
    ContactStatus.DO_NOT_CALL,
    ContactStatus.MEETING_BOOKED,
}


class InvalidTransition(Exception):
    """Raised when a contact is moved to a status that is not allowed."""


@dataclass
class Remark:
    at: datetime
    text: str

    def to_dict(self) -> dict:
        return {"at": self.at.isoformat(), "text": self.text}

    @classmethod
    def from_dict(cls, data: dict) -> Remark:
        return cls(at=datetime.fromisoformat(data["at"]), text=data["text"])


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Contact:
    name: str
    company: str = ""
    phone: str = ""
    email: str = ""
    id: str = field(default_factory=_new_id)
    status: ContactStatus = ContactStatus.NEW
    next_call_at: datetime | None = None
    meeting_at: datetime | None = None
    call_attempts: int = 0
    remarks: list[Remark] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Contact name is required")
        if not self.phone and not self.email:
            raise ValueError(f"Contact {self.name!r} needs a phone or an email")

    @property
    def is_closed(self) -> bool:
        """True when nobody should call this contact again."""
        # A final status is one with no allowed next steps.
        return not ALLOWED_TRANSITIONS[self.status]

    def add_remark(self, text: str, at: datetime) -> None:
        self.remarks.append(Remark(at=at, text=text))

    def transition_to(self, new_status: ContactStatus, at: datetime, remark: str = "") -> None:
        """Move to a new status, enforcing the allowed transitions."""
        if new_status not in ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransition(
                f"Contact {self.id} ({self.name}): cannot go from "
                f"{self.status.value} to {new_status.value}"
            )
        if new_status in CALL_OUTCOMES:
            self.call_attempts += 1
        self.status = new_status
        self.add_remark(remark or f"Status -> {new_status.value}", at)

    # --- conversion to/from plain dicts (for saving as JSON later) ---

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "company": self.company,
            "phone": self.phone,
            "email": self.email,
            "status": self.status.value,
            "next_call_at": self.next_call_at.isoformat() if self.next_call_at else None,
            "meeting_at": self.meeting_at.isoformat() if self.meeting_at else None,
            "call_attempts": self.call_attempts,
            "remarks": [r.to_dict() for r in self.remarks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Contact:
        return cls(
            id=data["id"],
            name=data["name"],
            company=data.get("company", ""),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            status=ContactStatus(data["status"]),
            next_call_at=_parse_dt(data.get("next_call_at")),
            meeting_at=_parse_dt(data.get("meeting_at")),
            call_attempts=data.get("call_attempts", 0),
            remarks=[Remark.from_dict(r) for r in data.get("remarks", [])],
        )


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
