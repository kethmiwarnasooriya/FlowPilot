"""Generates the sample documents in samples/ (fictional people and companies).

Run: .venv/bin/python scripts/make_samples.py
"""

from pathlib import Path

from docx import Document
from fpdf import FPDF

OUT = Path(__file__).resolve().parent.parent / "samples"

TABLE_CONTACTS = [
    ("Nimal Perera", "Lanka Tech Solutions", "+94 77 123 4567", "nimal.perera@example.com"),
    ("Ayesha Fernando", "Ceylon Exports Ltd", "+94 71 234 5678", "ayesha@example.com"),
    ("Kasun Silva", "Island Logistics", "077-345-6789", ""),
    ("Dilini Jayawardena", "Green Leaf Holdings", "", "dilini.j@example.com"),
]

PDF_CONTACTS = [
    ("Ruwan Bandara", "Colombo Digital", "+94 76 456 7890", "ruwan@example.com"),
    ("Sanduni Wickramasinghe", "Pearl Finance", "+94 70 567 8901", "sanduni.w@example.com"),
    ("Tharindu Rajapaksha", "Southern Agro", "0712223344", ""),
]


def make_contacts_docx() -> None:
    doc = Document()
    doc.add_heading("Business Contacts - Q4 Outreach", level=1)
    doc.add_paragraph(
        "Please schedule introductory calls with the following business contacts."
    )
    table = doc.add_table(rows=1, cols=4)
    for cell, title in zip(table.rows[0].cells, ("Name", "Company", "Phone", "Email")):
        cell.text = title
    for row in TABLE_CONTACTS:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = value
    doc.add_paragraph("Prepared by the Sales team.")
    doc.save(OUT / "contacts.docx")


def make_contacts_pdf() -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Business Contacts - Trade Fair Leads", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 7, "Leads collected at the trade fair. Please arrange follow-up calls.")
    pdf.ln(4)
    for name, company, phone, email in PDF_CONTACTS:
        for label, value in (("Name", name), ("Company", company),
                             ("Phone", phone), ("Email", email)):
            if value:
                pdf.cell(0, 7, f"{label}: {value}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
    pdf.output(str(OUT / "contacts.pdf"))


def make_meeting_notes_docx() -> None:
    doc = Document()
    doc.add_heading("Weekly Team Meeting Notes", level=1)
    doc.add_paragraph("Attendees: the whole sales team.")
    doc.add_paragraph("1. Reviewed last month's targets - 80% achieved.")
    doc.add_paragraph("2. New brochure design will be ready next week.")
    doc.add_paragraph("3. Office will be closed on the public holiday.")
    doc.save(OUT / "meeting_notes.docx")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    make_contacts_docx()
    make_contacts_pdf()
    make_meeting_notes_docx()
    print(f"Samples written to {OUT}")
