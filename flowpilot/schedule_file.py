"""The schedule text file shared between the scheduler (writer) and calendar sync (reader).

Format: JSON Lines - one complete JSON object per line, appended in time order.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# Entry types
CALL = "call"            # first call to a new contact
CALLBACK = "callback"    # follow-up call the contact asked for
MEETING = "meeting"      # physical meeting with an interested contact
CALL_TYPES = {CALL, CALLBACK}  # these occupy call slots


@dataclass(frozen=True)
class ScheduleEntry:
    entry_id: str          # unique; equals the queue message_uid that produced it
    type: str              # CALL, CALLBACK or MEETING
    contact_id: str
    name: str
    company: str
    phone: str
    email: str
    start: datetime
    duration_minutes: int
    created_at: datetime
    location: str = ""     # meetings only
    note: str = ""         # e.g. why a callback was requested

    def to_json(self) -> str:
        data = asdict(self)
        data["start"] = self.start.isoformat()
        data["created_at"] = self.created_at.isoformat()
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> ScheduleEntry:
        data = json.loads(line)
        data["start"] = datetime.fromisoformat(data["start"])
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


def append_entry(path: Path, entry: ScheduleEntry) -> None:
    """Append one line and force it to disk before returning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry.to_json() + "\n")  # one write call per complete line
        f.flush()
        os.fsync(f.fileno())  # make sure it is really on disk, not just in a buffer


def read_entries(path: Path) -> list[ScheduleEntry]:
    """Read all valid entries. A damaged line (e.g. half-written in a crash) is skipped."""
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                entries.append(ScheduleEntry.from_json(line))
            except (ValueError, TypeError, KeyError):
                print(f"warning: {path.name} line {line_no} is damaged and was skipped")
    return entries


def taken_call_slots(entries: list[ScheduleEntry]) -> list[datetime]:
    return [e.start for e in entries if e.type in CALL_TYPES]
