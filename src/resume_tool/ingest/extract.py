"""File → plain text. One function per format, no intelligence."""

from __future__ import annotations

from pathlib import Path


class UnsupportedFormat(ValueError):
    """Raised for a file extension we cannot extract text from."""


def extract_text(path: Path | str) -> str:
    """Extract plain text from a resume file (.txt, .md, .pdf, .docx)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _from_pdf(path)
    if suffix == ".docx":
        return _from_docx(path)
    raise UnsupportedFormat(
        f"cannot extract text from {suffix!r} — supported: .txt, .md, .pdf, .docx"
    )


def _from_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _from_docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    lines = [p.text for p in document.paragraphs]

    # Tables are bad for ATS parsing, but resumes still use them — read them anyway
    # so ingest does not silently drop content.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append("  ".join(cells))

    return "\n".join(lines)
