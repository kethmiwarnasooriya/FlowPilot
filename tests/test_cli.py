"""End-to-end tests through the command line (everything except the real Google API)."""

from pathlib import Path

import pytest

from flowpilot.cli import main
from flowpilot.contact_store import ContactStore
from flowpilot.models import ContactStatus
from flowpilot.schedule_file import read_entries

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def run(cfg, capsys):
    """run('list', '--status', 'new') -> (exit code, stdout, stderr)"""
    def _run(*argv):
        code = main([str(a) for a in argv], cfg=cfg)
        out = capsys.readouterr()
        return code, out.out, out.err
    return _run


def ids_by_name(cfg):
    store = ContactStore(cfg.contacts_store)
    result = {c.name: c.id for c in store.list()}
    store.close()
    return result


def test_full_flow(run, cfg):
    code, out, _ = run("ingest", SAMPLES / "contacts.pdf", SAMPLES / "meeting_notes.docx")
    assert code == 0
    assert "queued 3 contact(s)" in out
    assert "meeting_notes.docx: no business contacts found" in out

    code, out, _ = run("schedule")
    assert code == 0 and "Scheduled 3 call(s)" in out
    assert len(read_entries(cfg.schedule_file)) == 3

    ids = ids_by_name(cfg)
    assert run("callback", ids["Ruwan Bandara"], "--in", "2 weeks", "--remark", "Busy")[0] == 0
    assert run("not-interested", ids["Sanduni Wickramasinghe"], "--remark", "No budget")[0] == 0
    code, out, _ = run("meeting", ids["Tharindu Rajapaksha"], "--at", "2030-01-15 14:00",
                       "--location", "Galle office")
    assert code == 0 and "meeting booked" in out

    run("schedule")  # books the callback
    code, out, _ = run("list")
    assert "NOT_INTERESTED" in out and "MEETING_BOOKED" in out
    types = [e.type for e in read_entries(cfg.schedule_file)]
    assert types == ["call", "call", "call", "meeting", "callback"]


def test_list_filter_by_status(run, cfg):
    run("ingest", SAMPLES / "contacts.pdf")
    run("schedule")
    run("not-interested", ids_by_name(cfg)["Ruwan Bandara"], "--remark", "No", "--do-not-call")
    _, out, _ = run("list", "--status", "do_not_call")
    assert "Ruwan Bandara" in out and "Sanduni" not in out
    assert "1 contact(s)" in out


def test_show_contact_history(run, cfg):
    run("ingest", SAMPLES / "contacts.pdf")
    run("schedule")
    rid = ids_by_name(cfg)["Ruwan Bandara"]
    run("callback", rid, "--in", "3 days", "--remark", "Travelling")
    _, out, _ = run("show", rid)
    assert "Ruwan Bandara" in out and "+94764567890" in out
    assert "Call scheduled for" in out and "Asked to call back in 3 days: Travelling" in out


def test_user_errors_are_short_messages_not_tracebacks(run, cfg):
    run("ingest", SAMPLES / "contacts.pdf")
    run("schedule")
    rid = ids_by_name(cfg)["Ruwan Bandara"]

    code, _, err = run("callback", rid, "--in", "later")
    assert code == 1 and err.startswith("error: Can't understand 'later'")
    assert "Traceback" not in err

    code, _, err = run("show", "nope")
    assert code == 1 and "No contact with id 'nope'" in err

    code, _, err = run("meeting", rid, "--at", "next tuesday", "--location", "X")
    assert code == 1 and "YYYY-MM-DD HH:MM" in err

    code, _, err = run("ingest", SAMPLES / "missing.pdf")
    assert code == 1 and "No such file" in err


def test_do_not_call_then_callback_is_refused(run, cfg):
    run("ingest", SAMPLES / "contacts.pdf")
    run("schedule")
    rid = ids_by_name(cfg)["Ruwan Bandara"]
    run("not-interested", rid, "--remark", "Never again", "--do-not-call")
    code, _, err = run("callback", rid, "--in", "1 week")
    assert code == 1 and "cannot go from DO_NOT_CALL" in err
    store = ContactStore(cfg.contacts_store)
    assert store.get(rid).status is ContactStatus.DO_NOT_CALL
    store.close()


def test_missing_required_argument(run):
    with pytest.raises(SystemExit):   # argparse prints usage and exits
        run("not-interested", "abc")   # --remark is required
