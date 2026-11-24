"""Command-line interface. A thin layer: parse arguments, call the core functions, print results.

No business rules live here - they are all in the core modules (and tested there).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from flowpilot.config import Config, load_config
from flowpilot.contact_store import ContactNotFound, ContactStore
from flowpilot.message_queue import SQLiteQueue
from flowpilot.models import Contact, ContactStatus, InvalidTransition
from flowpilot.reader import UnsupportedDocument

# Errors caused by user input: show only the message, not a traceback.
USER_ERRORS = (ValueError, ContactNotFound, InvalidTransition, UnsupportedDocument, FileNotFoundError)


# ---------- commands ----------

def cmd_ingest(args, cfg: Config) -> None:
    from flowpilot.ingest import ingest_document

    queue, store = SQLiteQueue(cfg.queue_db), ContactStore(cfg.contacts_store)
    for path in args.files:
        report = ingest_document(path, queue, store, cfg.default_country_code)
        if not report.is_contact_document:
            print(f"{path}: no business contacts found - nothing queued")
            continue
        print(f"{path}: queued {len(report.queued)} contact(s)")
        for c in report.queued:
            print(f"  + {c.id}  {c.name}  {c.phone}")
        for reason in report.skipped:
            print(f"  - skipped: {reason}")
    print(f"Queue now holds {queue.pending_count()} message(s). Run 'schedule' to process them.")


def cmd_schedule(args, cfg: Config) -> None:
    from flowpilot.scheduler import run_scheduler

    queue, store = SQLiteQueue(cfg.queue_db), ContactStore(cfg.contacts_store)

    def once() -> None:
        report = run_scheduler(queue, store, cfg)
        for e in report.scheduled:
            print(f"  {e.start:%a %d %b %H:%M}  {e.type:8}  {e.contact_id}  {e.name}")
        for r in report.rejected:
            print(f"  rejected: {r}")
        if report.scheduled or not args.watch:
            print(f"Scheduled {len(report.scheduled)} call(s) into {cfg.schedule_file.name}.")

    if not args.watch:
        once()
        return
    print(f"Scheduler watching the queue every {cfg.sync_poll_seconds}s (Ctrl+C to stop)")
    while True:
        once()
        time.sleep(cfg.sync_poll_seconds)


def cmd_sync(args, cfg: Config) -> None:
    from flowpilot.calendar_client import GoogleCalendarClient
    from flowpilot.calendar_sync import sync_once, watch

    client = GoogleCalendarClient(cfg.credentials_file, cfg.token_file, cfg.calendar_id)
    if args.watch:
        watch(cfg, client)
        return
    report = sync_once(cfg, client)
    print(f"Created {len(report.created)} calendar event(s), "
          f"{len(report.already_existed)} already existed.")
    if report.error:
        print(f"Error: {report.error} - run again to retry the rest.")


def cmd_list(args, cfg: Config) -> None:
    store = ContactStore(cfg.contacts_store)
    status = ContactStatus(args.status.upper()) if args.status else None
    contacts = store.list(status)
    if not contacts:
        print("No contacts.")
        return
    print(f"{'ID':9} {'NAME':24} {'PHONE':14} {'STATUS':19} {'NEXT':14} LAST REMARK")
    for c in contacts:
        when = c.next_call_at or c.meeting_at
        when_text = f"{when:%d %b %H:%M}" if when else "-"
        remark = c.remarks[-1].text if c.remarks else ""
        if len(remark) > 45:
            remark = remark[:42] + "..."
        print(f"{c.id:9} {c.name[:24]:24} {c.phone:14} {c.status.value:19} {when_text:14} {remark}")
    print(f"\n{len(contacts)} contact(s)")


def cmd_show(args, cfg: Config) -> None:
    c: Contact = ContactStore(cfg.contacts_store).get(args.contact_id)
    print(f"{c.name}  ({c.id})")
    print(f"  Company : {c.company or '-'}")
    print(f"  Phone   : {c.phone}")
    print(f"  Email   : {c.email or '-'}")
    print(f"  Status  : {c.status.value}   (calls made: {c.call_attempts})")
    if c.next_call_at:
        print(f"  Next call : {c.next_call_at:%a %d %b %Y %H:%M}")
    if c.meeting_at:
        print(f"  Meeting   : {c.meeting_at:%a %d %b %Y %H:%M}")
    print("  History:")
    for r in c.remarks:
        print(f"    {r.at:%Y-%m-%d %H:%M}  {r.text}")


def cmd_callback(args, cfg: Config) -> None:
    from flowpilot.outcomes import record_callback

    queue, store = SQLiteQueue(cfg.queue_db), ContactStore(cfg.contacts_store)
    contact, not_before = record_callback(store, queue, args.contact_id, args.delay,
                                          args.remark or "", now=_now(cfg))
    print(f"{contact.name}: call back requested, not before {not_before:%a %d %b %Y}.")
    print("Run 'schedule' (or keep 'schedule --watch' running) to book the slot.")


def cmd_not_interested(args, cfg: Config) -> None:
    from flowpilot.outcomes import record_not_interested

    contact = record_not_interested(ContactStore(cfg.contacts_store), args.contact_id,
                                    args.remark, now=_now(cfg), do_not_call=args.do_not_call)
    print(f"{contact.name}: marked {contact.status.value}. They will not be called again.")


def cmd_meeting(args, cfg: Config) -> None:
    from flowpilot.outcomes import record_meeting

    try:
        meeting_at = datetime.fromisoformat(args.at)
    except ValueError:
        raise ValueError(f"Can't read the date {args.at!r}. Use 'YYYY-MM-DD HH:MM'.") from None
    entry = record_meeting(ContactStore(cfg.contacts_store), cfg, args.contact_id, meeting_at,
                           args.location, args.remark or "", now=_now(cfg))
    print(f"{entry.name}: meeting booked for {entry.start:%a %d %b %Y %H:%M} at {entry.location}.")
    print("Run 'sync' (or keep 'sync --watch' running) to add it to the calendar.")


def cmd_config(args, cfg: Config) -> None:
    print(f"Call interval   : every {cfg.call_interval_minutes} min ({cfg.call_duration_minutes}-min calls)")
    print(f"Working hours   : {cfg.working_hours_start:%H:%M}-{cfg.working_hours_end:%H:%M}")
    days = "Mon Tue Wed Thu Fri Sat Sun".split()
    print(f"Working days    : {' '.join(days[d] for d in cfg.working_days)}")
    print(f"Timezone        : {cfg.timezone}")
    print(f"Meeting length  : {cfg.meeting_duration_minutes} min")
    print(f"Schedule file   : {cfg.schedule_file}")
    print(f"Calendar        : {cfg.calendar_id}")


def _now(cfg: Config) -> datetime:
    return datetime.now(cfg.timezone)


# ---------- argument parsing ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flowpilot",
        description="Schedule business-contact calls from Word/PDF documents into Google Calendar.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    s = sub.add_parser("ingest", help="read documents and queue their business contacts")
    s.add_argument("files", nargs="+", help=".docx or .pdf files")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("schedule", help="give queued contacts a call slot in the schedule file")
    s.add_argument("--watch", action="store_true", help="keep running and check the queue regularly")
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("sync", help="create Google Calendar events for new schedule entries")
    s.add_argument("--watch", action="store_true", help="keep running and check the file regularly")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("list", help="list contacts and their status")
    s.add_argument("--status", choices=[st.value.lower() for st in ContactStatus],
                   type=str.lower, help="only show contacts with this status")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="show one contact with its full history")
    s.add_argument("contact_id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("callback", help="outcome: contact asked to be called again later")
    s.add_argument("contact_id")
    s.add_argument("--in", dest="delay", required=True, help="e.g. '3 days', '2 weeks', '1 month'")
    s.add_argument("--remark", help="optional note")
    s.set_defaults(func=cmd_callback)

    s = sub.add_parser("not-interested", help="outcome: contact is not interested")
    s.add_argument("contact_id")
    s.add_argument("--remark", required=True, help="why (required)")
    s.add_argument("--do-not-call", action="store_true", help="they asked never to be called again")
    s.set_defaults(func=cmd_not_interested)

    s = sub.add_parser("meeting", help="outcome: interested - book a physical meeting")
    s.add_argument("contact_id")
    s.add_argument("--at", required=True, help="date and time, 'YYYY-MM-DD HH:MM'")
    s.add_argument("--location", required=True, help="where the meeting takes place")
    s.add_argument("--remark", help="optional note")
    s.set_defaults(func=cmd_meeting)

    s = sub.add_parser("config", help="show the current settings")
    s.set_defaults(func=cmd_config)
    return p


def main(argv: list[str] | None = None, cfg: Config | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args, cfg or load_config())
    except USER_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0
