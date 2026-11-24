from pathlib import Path

import pytest

from flowpilot.reader import UnsupportedDocument, read_document

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_reads_docx_paragraphs_and_table_in_order():
    text = read_document(SAMPLES / "contacts.docx")
    lines = text.splitlines()
    assert lines[0] == "Business Contacts - Q4 Outreach"
    assert "Name | Company | Phone | Email" in lines
    assert "Nimal Perera | Lanka Tech Solutions | +94 77 123 4567 | nimal.perera@example.com" in lines
    # The paragraph after the table comes after the table rows.
    assert lines[-1] == "Prepared by the Sales team."


def test_reads_pdf():
    text = read_document(SAMPLES / "contacts.pdf")
    assert "Name: Ruwan Bandara" in text
    assert "Phone: 0712223344" in text


def test_extension_is_case_insensitive(tmp_path):
    copy = tmp_path / "CONTACTS.DOCX"
    copy.write_bytes((SAMPLES / "contacts.docx").read_bytes())
    assert "Nimal Perera" in read_document(copy)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        read_document(SAMPLES / "does_not_exist.pdf")


def test_unsupported_extension(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    with pytest.raises(UnsupportedDocument, match="Unsupported file type"):
        read_document(f)


def test_corrupted_file(tmp_path):
    f = tmp_path / "broken.pdf"
    f.write_text("this is not really a pdf")
    with pytest.raises(UnsupportedDocument, match="Could not read"):
        read_document(f)
