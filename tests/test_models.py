from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from flowpilot.models import Contact, ContactStatus, InvalidTransition

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=ZoneInfo("Asia/Colombo"))


def make_contact() -> Contact:
    return Contact(name="  Nimal Perera ", company="ABC Ltd", phone="+94771234567")


def test_new_contact_defaults():
    c = make_contact()
    assert c.name == "Nimal Perera"          # whitespace trimmed
    assert c.status is ContactStatus.NEW
    assert len(c.id) == 8
    assert not c.is_closed


def test_name_required():
    with pytest.raises(ValueError):
        Contact(name="   ", phone="123")


def test_phone_or_email_required():
    with pytest.raises(ValueError):
        Contact(name="No Way To Reach")


def test_happy_path_to_meeting():
    c = make_contact()
    c.transition_to(ContactStatus.SCHEDULED, NOW)
    c.transition_to(ContactStatus.MEETING_BOOKED, NOW, remark="Wants a demo")
    assert c.status is ContactStatus.MEETING_BOOKED
    assert c.call_attempts == 1
    assert c.remarks[-1].text == "Wants a demo"
    assert c.is_closed


def test_callback_loop():
    c = make_contact()
    c.transition_to(ContactStatus.SCHEDULED, NOW)
    c.transition_to(ContactStatus.CALLBACK_REQUESTED, NOW, remark="Call in 2 weeks")
    c.transition_to(ContactStatus.SCHEDULED, NOW)
    assert c.status is ContactStatus.SCHEDULED
    assert c.call_attempts == 1
    assert len(c.remarks) == 3


def test_cannot_call_do_not_call_contact_again():
    c = make_contact()
    c.transition_to(ContactStatus.SCHEDULED, NOW)
    c.transition_to(ContactStatus.DO_NOT_CALL, NOW, remark="Asked not to call")
    with pytest.raises(InvalidTransition):
        c.transition_to(ContactStatus.SCHEDULED, NOW)
    assert c.is_closed


def test_cannot_skip_scheduling():
    c = make_contact()
    with pytest.raises(InvalidTransition):
        c.transition_to(ContactStatus.MEETING_BOOKED, NOW)


def test_dict_round_trip():
    c = make_contact()
    c.transition_to(ContactStatus.SCHEDULED, NOW)
    c.next_call_at = NOW
    restored = Contact.from_dict(c.to_dict())
    assert restored == c
