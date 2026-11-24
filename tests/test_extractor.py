from pathlib import Path

import pytest

from flowpilot.extractor import extract_contacts, normalise_phone
from flowpilot.reader import read_document

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


# ---------- whole documents ----------

def test_docx_table_contacts():
    result = extract_contacts(read_document(SAMPLES / "contacts.docx"))
    assert [c.name for c in result.contacts] == [
        "Nimal Perera", "Ayesha Fernando", "Kasun Silva",
    ]
    nimal = result.contacts[0]
    assert nimal.company == "Lanka Tech Solutions"
    assert nimal.phone == "+94771234567"
    assert nimal.email == "nimal.perera@example.com"
    # Dilini has only an email, so she can't be called.
    assert result.skipped == ["Dilini Jayawardena: skipped (no phone number - cannot be called)"]


def test_pdf_block_contacts_without_blank_lines():
    result = extract_contacts(read_document(SAMPLES / "contacts.pdf"))
    assert [c.name for c in result.contacts] == [
        "Ruwan Bandara", "Sanduni Wickramasinghe", "Tharindu Rajapaksha",
    ]
    # Tharindu has no email - his fields must not leak into the previous contact.
    assert result.contacts[1].phone == "+94705678901"
    assert result.contacts[2].email == ""


def test_non_contact_document():
    result = extract_contacts(read_document(SAMPLES / "meeting_notes.docx"))
    assert not result.is_contact_document
    assert result.contacts == []


# ---------- layouts and aliases ----------

def test_valid_email_but_invalid_phone_is_skipped():
    result = extract_contacts("Name: X\nPhone: 12\nEmail: x@example.com")
    assert result.contacts == []
    assert result.skipped == ["X: skipped (invalid phone '12')"]


def test_label_aliases():
    text = "Contact Person: Amal\nOrganisation: XYZ\nMobile: 0771112222\nE-mail: amal@example.com"
    [c] = extract_contacts(text).contacts
    assert (c.name, c.company, c.phone, c.email) == ("Amal", "XYZ", "+94771112222", "amal@example.com")


def test_table_with_different_column_order():
    text = "Email | Full Name | Tel\nk@example.com | Kamal | 0779998888"
    [c] = extract_contacts(text).contacts
    assert (c.name, c.phone, c.email) == ("Kamal", "+94779998888", "k@example.com")


def test_text_after_table_is_not_treated_as_a_row():
    text = "Name | Phone\nA | 0771234567\nSome paragraph\nB | 0771234568"
    assert [c.name for c in extract_contacts(text).contacts] == ["A"]


# ---------- validation ----------

def test_invalid_contact_is_skipped_with_reason():
    text = "Name: Bad Data\nPhone: 123\nEmail: not-an-email"
    result = extract_contacts(text)
    assert result.contacts == []
    assert result.skipped == ["Bad Data: skipped (invalid phone '123'; invalid email 'not-an-email')"]


def test_invalid_email_dropped_but_contact_kept_if_phone_ok():
    [c] = extract_contacts("Name: Ok\nPhone: 0771234567\nEmail: broken@").contacts
    assert c.phone == "+94771234567" and c.email == ""


def test_duplicates_removed_even_with_different_phone_formats():
    text = "Name: Same Person\nPhone: 077 123 4567\nName: Same Person Again\nPhone: +94-77-123-4567"
    result = extract_contacts(text)
    assert len(result.contacts) == 1
    assert "duplicate" in result.skipped[0]


@pytest.mark.parametrize("raw, expected", [
    ("+94 77 123 4567", "+94771234567"),
    ("077-123-4567", "+94771234567"),
    ("0771234567", "+94771234567"),
    ("0094771234567", "+94771234567"),
    ("(077) 123 4567", "+94771234567"),
    ("+44 20 7946 0958", "+442079460958"),
    ("123", None),
])
def test_normalise_phone(raw, expected):
    assert normalise_phone(raw, "+94") == expected


def test_country_code_is_configurable():
    assert normalise_phone("0412345678", "+61") == "+61412345678"
