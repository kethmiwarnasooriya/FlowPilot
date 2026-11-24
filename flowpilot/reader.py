"""Turns a Word (.docx) or PDF document into plain text.

This module only knows about file formats. Finding contacts in the text is
the extractor's job, so new formats can be added here without touching it.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.table import Table
from pypdf import PdfReader


class UnsupportedDocument(Exception):
    """Raised when the file type is not supported or the file cannot be read."""


def read_document(path: str | Path) -> str:
    """Return the text content of a .docx or .pdf file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")

    readers = {
        ".docx": _read_docx,
        ".pdf": _read_pdf,
    }
    reader = readers.get(path.suffix.lower())
    if reader is None:
        raise UnsupportedDocument(
            f"Unsupported file type {path.suffix!r}. Supported: {', '.join(readers)}"
        )

    try:
        text = reader(path)
    except Exception as exc:  # corrupted / password-protected / not really that format
        raise UnsupportedDocument(f"Could not read {path.name}: {exc}") from exc

    return _normalise(text)


def _read_docx(path: Path) -> str:
    """Read paragraphs and tables in the order they appear in the document."""
    lines: list[str] = []
    for block in Document(str(path)).iter_inner_content():
        if isinstance(block, Table):
            for row in block.rows:
                # One table row becomes one line, cells separated by " | ".
                lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        else:
            lines.append(block.text)
    return "\n".join(lines)


def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise UnsupportedDocument("PDF is password protected")
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _normalise(text: str) -> str:
    """Trim each line and collapse runs of blank lines into a single one."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
