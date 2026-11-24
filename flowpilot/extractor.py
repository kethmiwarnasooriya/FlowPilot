"""Finds business contacts in plain text produced by the reader.

Two layouts are supported:
  1. Tables:            Name | Company | Phone | Email
                        Nimal Perera | Lanka Tech | +94 77 123 4567 | nimal@example.com
  2. Labelled blocks:   Name: Ruwan Bandara
                        Phone: +94 76 456 7890
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from flowpilot.models import Contact

# Different words people use for the same field.
FIELD_ALIASES: dict[str, str] = {
    "name": "name", "full name": "name", "contact name": "name", "contact person": "name",
    "company": "company", "company name": "company", "organisation": "company",
    "organization": "company", "business": "company",
    "phone": "phone", "phone number": "phone", "mobile": "phone", "mobile number": "phone",
    "tel": "phone", "telephone": "phone", "contact number": "phone",
    "email": "email", "e-mail": "email", "email address": "email", "mail": "email",
}

KEY_VALUE_RE = re.compile(r"^([A-Za-z][A-Za-z \-]{0,30}?)\s*:\s*(.*)$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


@dataclass
class ExtractionResult:
    contacts: list[Contact] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # human-readable reasons

    @property
    def is_contact_document(self) -> bool:
        return bool(self.contacts)


def extract_contacts(text: str, default_country_code: str = "+94") -> ExtractionResult:
    records = _parse_tables(text) + _parse_labelled_blocks(text)

    result = ExtractionResult()
    seen: set[str] = set()
    for record in records:
        contact, problem = _build_contact(record, default_country_code)
        if problem:
            result.skipped.append(problem)
            continue
        key = contact.phone or contact.email.lower()
        if key in seen:
            result.skipped.append(f"{contact.name}: duplicate of an earlier contact")
            continue
        seen.add(key)
        result.contacts.append(contact)
    return result


# ---------- Strategy 1: tables ----------

def _parse_tables(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    columns: list[str | None] | None = None  # field name for each column, while inside a table

    for line in text.splitlines():
        if "|" not in line:
            columns = None  # a non-table line ends the current table
            continue
        cells = [c.strip() for c in line.split("|")]
        header = [FIELD_ALIASES.get(c.lower()) for c in cells]
        if "name" in header and ("phone" in header or "email" in header):
            columns = header  # this line is a header row
            continue
        if columns is None or len(cells) != len(columns):
            continue
        records.append({f: v for f, v in zip(columns, cells) if f and v})
    return records


# ---------- Strategy 2: "Label: value" blocks ----------

def _parse_labelled_blocks(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for line in text.splitlines():
        match = KEY_VALUE_RE.match(line)
        if not match:
            continue
        field_name = FIELD_ALIASES.get(match.group(1).strip().lower())
        value = match.group(2).strip()
        if not field_name or not value:
            continue
        # A new "Name:" starts the next contact. We can't rely on blank lines,
        # because PDF text extraction often loses them.
        if field_name == "name" and "name" in current:
            records.append(current)
            current = {}
        current[field_name] = value

    if current:
        records.append(current)
    # Ignore blocks that never had a name (e.g. a stray "Email:" line in a letter footer).
    return [r for r in records if "name" in r]


# ---------- Cleaning and validation ----------

def normalise_phone(raw: str, default_country_code: str) -> str | None:
    """Convert to E.164 (+94771234567). Returns None if it isn't a plausible number."""
    has_plus = raw.strip().startswith("+")
    digits = re.sub(r"\D", "", raw)
    if has_plus:
        number = "+" + digits
    elif digits.startswith("00"):          # 0094... international prefix
        number = "+" + digits[2:]
    elif digits.startswith("0"):           # local format 077...
        number = default_country_code + digits[1:]
    else:
        number = "+" + digits
    # E.164: up to 15 digits; 8 is a sensible minimum for a real number.
    return number if 8 <= len(number) - 1 <= 15 else None


def _build_contact(record: dict[str, str], cc: str) -> tuple[Contact | None, str | None]:
    name = record.get("name", "").strip()
    if not name:
        return None, "Record without a name"

    problems = []
    phone = ""
    if record.get("phone"):
        phone = normalise_phone(record["phone"], cc) or ""
        if not phone:
            problems.append(f"invalid phone {record['phone']!r}")
    email = record.get("email", "").strip()
    if email and not EMAIL_RE.match(email):
        problems.append(f"invalid email {email!r}")
        email = ""

    # Contacts are scheduled for *calling*, so a valid phone number is required.
    if not phone:
        reason = "; ".join(problems) or "no phone number - cannot be called"
        return None, f"{name}: skipped ({reason})"

    contact = Contact(name=name, company=record.get("company", ""), phone=phone, email=email)
    return contact, None
