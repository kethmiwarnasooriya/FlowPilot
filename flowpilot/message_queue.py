"""A persistent FIFO message queue.

Producer (ingest) --put--> [ queue ] --get--> Consumer (scheduler) --ack--> removed

`get` does not delete a message; it marks it as in progress. The consumer calls
`ack` only after it has finished its work, so a crash in between never loses a
message - `recover` puts unfinished messages back in line.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Protocol

PENDING = "pending"
IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class Message:
    id: int
    body: dict


class MessageQueue(Protocol):
    """Any queue implementation (SQLite, in-memory, Redis, RabbitMQ...) must offer these."""

    def put(self, body: dict) -> int: ...
    def get(self) -> Message | None: ...
    def ack(self, message_id: int) -> None: ...
    def release(self, message_id: int) -> None: ...
    def recover(self) -> int: ...
    def pending_count(self) -> int: ...


class SQLiteQueue:
    """Queue stored in a SQLite file, so it survives restarts and works across processes."""

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: we control transactions ourselves (BEGIN ... COMMIT).
        self._db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                   id     INTEGER PRIMARY KEY AUTOINCREMENT,
                   body   TEXT    NOT NULL,
                   status TEXT    NOT NULL DEFAULT 'pending'
               )"""
        )

    def put(self, body: dict) -> int:
        cur = self._db.execute("INSERT INTO messages (body) VALUES (?)", (json.dumps(body),))
        return cur.lastrowid

    def get(self) -> Message | None:
        """Claim the oldest pending message, or return None if the queue is empty."""
        # BEGIN IMMEDIATE locks the database for writing, so two consumers
        # running at the same time can never claim the same message.
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT id, body FROM messages WHERE status = ? ORDER BY id LIMIT 1",
                (PENDING,),
            ).fetchone()
            if row:
                self._db.execute(
                    "UPDATE messages SET status = ? WHERE id = ?", (IN_PROGRESS, row[0])
                )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        return Message(id=row[0], body=json.loads(row[1])) if row else None

    def ack(self, message_id: int) -> None:
        """Work finished successfully - remove the message for good."""
        self._db.execute("DELETE FROM messages WHERE id = ?", (message_id,))

    def release(self, message_id: int) -> None:
        """Work failed - put the message back so it can be tried again."""
        self._db.execute(
            "UPDATE messages SET status = ? WHERE id = ?", (PENDING, message_id)
        )

    def recover(self) -> int:
        """After a crash: return all in-progress messages to the queue."""
        cur = self._db.execute(
            "UPDATE messages SET status = ? WHERE status = ?", (PENDING, IN_PROGRESS)
        )
        return cur.rowcount

    def pending_count(self) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE status = ?", (PENDING,)
        ).fetchone()[0]

    def close(self) -> None:
        self._db.close()


class InMemoryQueue:
    """Same behaviour without persistence - handy for tests and quick experiments."""

    def __init__(self) -> None:
        self._ids = count(1)
        self._pending: deque[Message] = deque()
        self._in_progress: dict[int, Message] = {}

    def put(self, body: dict) -> int:
        msg = Message(id=next(self._ids), body=body)
        self._pending.append(msg)
        return msg.id

    def get(self) -> Message | None:
        if not self._pending:
            return None
        msg = self._pending.popleft()
        self._in_progress[msg.id] = msg
        return msg

    def ack(self, message_id: int) -> None:
        self._in_progress.pop(message_id, None)

    def release(self, message_id: int) -> None:
        msg = self._in_progress.pop(message_id, None)
        if msg:
            self._pending.appendleft(msg)

    def recover(self) -> int:
        n = len(self._in_progress)
        for msg in sorted(self._in_progress.values(), key=lambda m: m.id, reverse=True):
            self._pending.appendleft(msg)
        self._in_progress.clear()
        return n

    def pending_count(self) -> int:
        return len(self._pending)
