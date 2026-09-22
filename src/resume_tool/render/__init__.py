"""Render a resume to an ATS-safe document and verify it survives parsing."""

from .document import Contact, Entry, ResumeDoc, Section
from .lint import Issue, format_issues, lint_docx
from .roundtrip import RoundTripResult, verify_roundtrip
from .writer import write_docx

__all__ = [
    "Contact",
    "Entry",
    "Issue",
    "ResumeDoc",
    "RoundTripResult",
    "Section",
    "format_issues",
    "lint_docx",
    "verify_roundtrip",
    "write_docx",
]
