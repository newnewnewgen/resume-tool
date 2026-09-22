"""Structured representation of a resume document.

Deliberately format-agnostic: the writer turns this into .docx, the round-trip
parser turns a .docx back into this, and the two are compared.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Contact:
    name: str
    location: str = ""
    phone: str = ""
    email: str = ""
    linkedin: str = ""
    website: str = ""

    def detail_line(self) -> str:
        parts = [self.location, self.phone, self.email, self.linkedin, self.website]
        return " | ".join(p for p in parts if p)


@dataclass
class Entry:
    """One role, or one leadership position."""

    title: str
    organization: str
    start_date: str = ""
    end_date: str = ""          # blank means current
    location: str = ""
    bullets: list[str] = field(default_factory=list)

    @property
    def date_range(self) -> str:
        if not self.start_date:
            return ""
        return f"{self.start_date} – {self.end_date or 'Present'}"


@dataclass
class Section:
    """A resume section. Either dated entries, or free lines (skills, education)."""

    heading: str
    entries: list[Entry] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    @property
    def is_entry_section(self) -> bool:
        return bool(self.entries)


@dataclass
class ResumeDoc:
    contact: Contact
    summary: str = ""
    sections: list[Section] = field(default_factory=list)

    def all_bullets(self) -> list[str]:
        return [b for s in self.sections for e in s.entries for b in e.bullets]

    def all_entries(self) -> list[Entry]:
        return [e for s in self.sections for e in s.entries]
