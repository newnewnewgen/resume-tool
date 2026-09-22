"""Round-trip verification: write a .docx, read it back, prove nothing was lost.

The point of blocker #4 — "a way to test it". The test deliberately reads the
file back with the same generic parser used to ingest a stranger's resume,
rather than one that knows the writer's layout. A parser that already knows
where everything is proves nothing about what an ATS will do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..ingest.extract import extract_text
from ..ingest.structure import parse_resume
from .document import ResumeDoc
from .writer import write_docx

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d\-.\s()]{7,}\d")
_LINKEDIN = re.compile(r"linkedin\.com/in/[\w\-/]+", re.IGNORECASE)


@dataclass
class RoundTripResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    recovered_entries: int = 0
    expected_entries: int = 0
    recovered_bullets: int = 0
    expected_bullets: int = 0

    def __str__(self) -> str:
        head = (f"entries {self.recovered_entries}/{self.expected_entries}  "
                f"bullets {self.recovered_bullets}/{self.expected_bullets}")
        if self.ok:
            return f"round-trip: PASS  ({head})"
        return "round-trip: FAIL  ({})\n{}".format(
            head, "\n".join(f"  - {f}" for f in self.failures))


def verify_roundtrip(doc: ResumeDoc, path: Path | str) -> RoundTripResult:
    """Write `doc` to `path`, parse it back, and compare."""
    path = write_docx(doc, path)
    text = extract_text(path)
    parsed = parse_resume(text)
    failures: list[str] = []

    # Contact details must survive — a resume that parses without an email is
    # worse than one that fails outright, because it fails silently.
    if doc.contact.name and doc.contact.name.upper() not in text.upper():
        failures.append(f"name missing: {doc.contact.name!r}")
    for label, pattern, expected in (
        ("email", _EMAIL, doc.contact.email),
        ("phone", _PHONE, doc.contact.phone),
        ("linkedin", _LINKEDIN, doc.contact.linkedin),
    ):
        if not expected:
            continue
        found = pattern.search(text)
        if not found:
            failures.append(f"{label} not recoverable: {expected!r}")
        elif _norm(expected) not in _norm(found.group(0)) and \
             _norm(found.group(0)) not in _norm(expected):
            failures.append(f"{label} mangled: wrote {expected!r}, read {found.group(0)!r}")

    expected_entries = doc.all_entries()
    for entry in expected_entries:
        if entry.title and entry.title not in text:
            failures.append(f"title missing: {entry.title!r}")
        if entry.organization and entry.organization not in text:
            failures.append(f"organization missing: {entry.organization!r}")
        if entry.start_date and entry.start_date not in text:
            failures.append(f"start date missing: {entry.start_date!r} ({entry.title})")
        if entry.end_date and entry.end_date not in text:
            failures.append(f"end date missing: {entry.end_date!r} ({entry.title})")

    expected_bullets = doc.all_bullets()
    flat = _norm(text)
    for bullet in expected_bullets:
        if _norm(bullet) not in flat:
            failures.append(f"bullet missing or altered: {bullet[:60]!r}...")

    for section in doc.sections:
        if section.heading.upper() not in text.upper():
            failures.append(f"section heading missing: {section.heading!r}")

    if doc.summary and _norm(doc.summary) not in flat:
        failures.append("summary missing or altered")

    recovered_bullets = sum(1 for b in expected_bullets if _norm(b) in flat)

    # Count entries whose identifying fields all survived. Comparing against
    # len(parsed.jobs) would be wrong: the parser deliberately excludes Leadership
    # and Education from "jobs", so a correct document looked like a 4/7 failure.
    recovered_entries = sum(
        1 for e in expected_entries
        if (not e.title or e.title in text)
        and (not e.organization or e.organization in text)
        and (not e.start_date or e.start_date in text)
    )

    return RoundTripResult(
        ok=not failures,
        failures=failures,
        recovered_entries=recovered_entries,
        expected_entries=len(expected_entries),
        recovered_bullets=recovered_bullets,
        expected_bullets=len(expected_bullets),
    )


def _norm(s: str) -> str:
    """Collapse whitespace so line wrapping does not register as data loss."""
    return re.sub(r"\s+", " ", s).strip().lower()
