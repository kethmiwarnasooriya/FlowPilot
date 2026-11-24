"""FlowPilot web dashboard - a thin UI over the same functions the command line uses.

Run with:  streamlit run dashboard.py
"""

from __future__ import annotations

import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

import streamlit as st

from flowpilot.calendar_sync import load_state
from flowpilot.cli import USER_ERRORS
from flowpilot.config import load_config
from flowpilot.contact_store import ContactStore
from flowpilot.ingest import ingest_document
from flowpilot.message_queue import SQLiteQueue
from flowpilot.models import ContactStatus
from flowpilot.outcomes import record_callback, record_meeting, record_not_interested
from flowpilot.schedule_file import read_entries
from flowpilot.scheduler import run_scheduler

st.set_page_config(page_title="FlowPilot", page_icon="📞", layout="wide")

cfg = load_config()
# Opened on every rerun: SQLite connections must not be shared between Streamlit's threads.
store = ContactStore(cfg.contacts_store)
queue = SQLiteQueue(cfg.queue_db)


def now() -> datetime:
    return datetime.now(cfg.timezone)


def flash(kind: str, message: str) -> None:
    """Show a message after the page reloads with fresh data."""
    st.session_state["flash"] = (kind, message)
    st.rerun()


# ---------------- sidebar: input and pipeline ----------------

with st.sidebar:
    st.header("1. Add documents")
    uploads = st.file_uploader("Word or PDF files", type=["docx", "pdf"], accept_multiple_files=True)
    if st.button("Read & queue contacts", disabled=not uploads, use_container_width=True):
        lines = []
        with tempfile.TemporaryDirectory() as tmp:
            for upload in uploads:
                path = Path(tmp) / upload.name
                path.write_bytes(upload.getvalue())
                try:
                    report = ingest_document(path, queue, store, cfg.default_country_code)
                except USER_ERRORS as exc:
                    lines.append(f"**{upload.name}**: error - {exc}")
                    continue
                if not report.is_contact_document:
                    lines.append(f"**{upload.name}**: no business contacts found")
                    continue
                lines.append(f"**{upload.name}**: queued {len(report.queued)} contact(s)")
                lines += [f"- skipped: {s}" for s in report.skipped]
        flash("info", "\n\n".join(lines))

    st.header("2. Run the pipeline")
    st.caption(f"Messages waiting in queue: **{queue.pending_count()}**")
    if st.button("Run scheduler", use_container_width=True):
        report = run_scheduler(queue, store, cfg)
        msg = f"Scheduled {len(report.scheduled)} call(s)."
        msg += "".join(f"\n\n- {e.start:%a %d %b %H:%M} · {e.name}" for e in report.scheduled)
        msg += "".join(f"\n\n- rejected: {r}" for r in report.rejected)
        flash("success", msg)

    if st.button("Sync to Google Calendar", use_container_width=True):
        if not cfg.token_file.exists():
            flash("error", "Not signed in to Google yet. Run `python -m flowpilot sync` once "
                           "in a terminal to sign in, then use this button.")
        from flowpilot.calendar_client import GoogleCalendarClient
        from flowpilot.calendar_sync import sync_once
        try:
            client = GoogleCalendarClient(cfg.credentials_file, cfg.token_file, cfg.calendar_id)
            report = sync_once(cfg, client)
        except Exception as exc:  # network / Google problems: show them, don't crash the page
            flash("error", f"Sync failed: {exc}")
        msg = f"Created {len(report.created)} calendar event(s)."
        if report.error:
            flash("warning", msg + f" Stopped early: {report.error}. Press again to retry.")
        flash("success", msg)

    st.divider()
    st.caption(
        f"Calls every {cfg.call_interval_minutes} min · "
        f"{cfg.working_hours_start:%H:%M}-{cfg.working_hours_end:%H:%M} · {cfg.timezone}"
    )


# ---------------- main area ----------------

st.title("📞 FlowPilot")

if "flash" in st.session_state:
    kind, message = st.session_state.pop("flash")
    getattr(st, kind)(message)

contacts = store.list()
counts = {s: sum(c.status is s for c in contacts) for s in ContactStatus}
cols = st.columns(len(ContactStatus))
for col, status in zip(cols, ContactStatus, strict=True):
    col.metric(status.value.replace("_", " ").title(), counts[status])

tab_contacts, tab_schedule = st.tabs(["Contacts", "Schedule file"])

with tab_contacts:
    status_filter = st.multiselect(
        "Filter by status", [s.value for s in ContactStatus], placeholder="All statuses")
    shown = [c for c in contacts if not status_filter or c.status.value in status_filter]
    st.dataframe(
        [{
            "ID": c.id,
            "Name": c.name,
            "Company": c.company,
            "Phone": c.phone,
            "Status": c.status.value,
            "Next": f"{(c.next_call_at or c.meeting_at):%a %d %b %H:%M}"
                    if (c.next_call_at or c.meeting_at) else "",
            "Last remark": c.remarks[-1].text if c.remarks else "",
        } for c in shown],
        hide_index=True, use_container_width=True,
    )

    if contacts:
        st.subheader("Contact details & call outcome")
        chosen = st.selectbox(
            "Contact", contacts,
            format_func=lambda c: f"{c.name} · {c.phone} · {c.status.value} ({c.id})",
        )
        left, right = st.columns(2)

        with left:
            st.markdown(f"**{chosen.name}** · {chosen.company or '-'}  \n"
                        f"📞 {chosen.phone}  \n✉️ {chosen.email or '-'}  \n"
                        f"Status: `{chosen.status.value}` · calls made: {chosen.call_attempts}")
            st.markdown("**History**")
            for r in reversed(chosen.remarks):
                st.markdown(f"- `{r.at:%Y-%m-%d %H:%M}` {r.text}")

        with right:
            if chosen.status is not ContactStatus.SCHEDULED:
                st.info("Outcomes can be recorded for contacts with a scheduled call.")
            else:
                outcome = st.radio(
                    "What happened on the call?",
                    ["Call back later", "Not interested", "Do not call again", "Interested - book meeting"],
                )
                with st.form("outcome", clear_on_submit=True):
                    if outcome == "Call back later":
                        amount = st.number_input("Call back in", min_value=1, max_value=24, value=2)
                        unit = st.selectbox("Unit", ["days", "weeks", "months"], index=1)
                    elif outcome == "Interested - book meeting":
                        tomorrow = (now() + timedelta(days=1)).date()
                        day = st.date_input("Meeting date", value=tomorrow, min_value=now().date())
                        at = st.time_input("Meeting time", value=time(10, 0), step=timedelta(minutes=15))
                        location = st.text_input("Location")
                    remark = st.text_area(
                        "Remark" + (" (required)" if outcome in ("Not interested", "Do not call again") else ""))
                    submitted = st.form_submit_button("Save outcome", type="primary")

                if submitted:
                    try:
                        if outcome == "Call back later":
                            delay = f"{amount} {unit}"
                            _, not_before = record_callback(store, queue, chosen.id, delay, remark, now())
                            run_scheduler(queue, store, cfg)  # book the slot right away
                            booked = store.get(chosen.id).next_call_at
                            flash("success", f"{chosen.name}: follow-up call booked for "
                                             f"{booked:%a %d %b %H:%M}. Press **Sync** to add it to the calendar.")
                        elif outcome in ("Not interested", "Do not call again"):
                            c = record_not_interested(store, chosen.id, remark, now(),
                                                      do_not_call=outcome == "Do not call again")
                            flash("success", f"{c.name} marked {c.status.value}.")
                        else:
                            meeting_at = datetime.combine(day, at, tzinfo=cfg.timezone)
                            e = record_meeting(store, cfg, chosen.id, meeting_at, location, remark, now())
                            flash("success", f"Meeting with {e.name} booked for {e.start:%a %d %b %H:%M} "
                                             f"at {e.location}. Press **Sync** to add it to the calendar.")
                    except USER_ERRORS as exc:
                        st.error(str(exc))
    else:
        st.info("No contacts yet - upload a Word or PDF document in the sidebar.")

with tab_schedule:
    st.caption(f"`{cfg.schedule_file}` - written by the scheduler, read by the calendar sync process.")
    entries = read_entries(cfg.schedule_file)
    synced = load_state(cfg.sync_state_file)
    if entries:
        st.dataframe(
            [{
                "Start": f"{e.start:%a %d %b %Y %H:%M}",
                "Type": e.type,
                "Name": e.name,
                "Phone": e.phone,
                "Location": e.location,
                "In calendar": "✅" if e.entry_id in synced else "⏳ not yet",
            } for e in sorted(entries, key=lambda e: e.start)],
            hide_index=True, use_container_width=True,
        )
    else:
        st.info("The schedule is empty.")
