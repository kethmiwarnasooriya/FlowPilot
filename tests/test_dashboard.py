"""Runs the Streamlit dashboard headlessly against a temporary config."""

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")  # skipped if the UI extras aren't installed

from flowpilot.config import DEFAULT_CONFIG_PATH  # noqa: E402
from flowpilot.contact_store import ContactStore  # noqa: E402
from flowpilot.ingest import ingest_document  # noqa: E402
from flowpilot.message_queue import SQLiteQueue  # noqa: E402
from flowpilot.models import ContactStatus  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


@pytest.fixture
def ui_cfg(tmp_path, monkeypatch, cfg):
    """A config file whose data paths point into tmp_path, used via FLOWPILOT_CONFIG."""
    text = DEFAULT_CONFIG_PATH.read_text()
    for key in ("queue_db", "schedule_file", "sync_state_file", "contacts_store"):
        old = next(line for line in text.splitlines() if line.startswith(f"{key} ="))
        text = text.replace(old, f'{key} = "{tmp_path / key}"')
    path = tmp_path / "config.toml"
    path.write_text(text)
    monkeypatch.setenv("FLOWPILOT_CONFIG", str(path))
    from flowpilot.config import load_config
    return load_config()


def app():
    return st_testing.AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=30)


def test_empty_dashboard_renders(ui_cfg):
    at = app().run()
    assert not at.exception
    assert at.title[0].value == "📞 FlowPilot"
    assert any("No contacts yet" in i.value for i in at.info)


def test_scheduler_button_and_contacts_table(ui_cfg):
    store, q = ContactStore(ui_cfg.contacts_store), SQLiteQueue(ui_cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q, store)

    at = app().run()
    at.button[1].click().run()          # "Run scheduler"
    assert not at.exception
    assert "Scheduled 3 call(s)" in at.success[0].value
    assert len(at.dataframe[0].value) == 3
    assert all(s.status is ContactStatus.SCHEDULED for s in store.list())


def test_record_not_interested_from_the_form(ui_cfg):
    store, q = ContactStore(ui_cfg.contacts_store), SQLiteQueue(ui_cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    at = app().run()
    at.button[1].click().run()          # schedule them

    at.radio[0].set_value("Not interested").run()
    at.text_area[0].input("No budget this year")
    at.button(key="FormSubmitter:outcome-Save outcome").click().run()
    assert not at.exception
    assert "marked NOT_INTERESTED" in at.success[0].value
    assert store.list(ContactStatus.NOT_INTERESTED)[0].remarks[-1].text == "No budget this year"


def test_missing_remark_shows_error_not_crash(ui_cfg):
    store, q = ContactStore(ui_cfg.contacts_store), SQLiteQueue(ui_cfg.queue_db)
    ingest_document(SAMPLES / "contacts.pdf", q, store)
    at = app().run()
    at.button[1].click().run()

    at.radio[0].set_value("Do not call again").run()
    at.button(key="FormSubmitter:outcome-Save outcome").click().run()
    assert not at.exception
    assert "remark" in at.error[0].value.lower()
