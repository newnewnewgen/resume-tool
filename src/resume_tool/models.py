"""Domain models mirroring the schema.

Kept as plain dataclasses: the store owns all SQL, these own shape and display.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class FactKind(StrEnum):
    METRIC = "metric"
    TECHNOLOGY = "technology"
    SCOPE = "scope"
    COLLABORATOR = "collaborator"
    OUTCOME = "outcome"


class Tier(StrEnum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NICE_TO_HAVE = "nice_to_have"


class RequirementKind(StrEnum):
    KNOCKOUT = "knockout"
    SKILL = "skill"
    QUALITY = "quality"


class MatchState(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    GAP = "gap"


# ── Dates ───────────────────────────────────────────────────────────────────
#
# Stored as 'YYYY' or 'YYYY-MM'. Resumes rarely carry day precision, and month
# precision is what ordering and duration need.

_DATE_RE = re.compile(r"^(?P<year>\d{4})(?:-(?P<month>\d{2}))?(?:-\d{2})?$")


class InvalidDate(ValueError):
    """Raised when a date is not 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD'."""


def validate_date(value: str | None, *, allow_none: bool = True) -> str | None:
    """Normalize a date to 'YYYY' or 'YYYY-MM', else raise.

    Day precision is accepted and truncated: resumes do not use it, and writing a full
    date into a draft by hand is a natural thing to do.
    """
    if value is None:
        if allow_none:
            return None
        raise InvalidDate("date is required")

    value = value.strip()
    match = _DATE_RE.match(value)
    if not match:
        raise InvalidDate(f"expected 'YYYY' or 'YYYY-MM', got {value!r}")

    month = match.group("month")
    if month is None:
        return match.group("year")
    if not 1 <= int(month) <= 12:
        raise InvalidDate(f"month out of range in {value!r}")
    return f"{match.group('year')}-{month}"


def date_sort_key(value: str | None) -> tuple[int, int]:
    """Sort key for a stored date. None sorts last (a current role is most recent)."""
    if value is None:
        return (9999, 99)
    parts = value.split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 0
    return (year, month)


# ── Entities ────────────────────────────────────────────────────────────────


@dataclass
class Job:
    employer: str
    title: str
    start_date: str
    end_date: str | None = None
    location: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        self.start_date = validate_date(self.start_date, allow_none=False)  # type: ignore[assignment]
        self.end_date = validate_date(self.end_date)

    @property
    def display_id(self) -> str:
        return f"JOB-{self.id:03d}" if self.id is not None else "JOB-???"

    @property
    def date_range(self) -> str:
        return f"{self.start_date} – {self.end_date or 'Present'}"

    def __str__(self) -> str:
        return f"{self.title} @ {self.employer} ({self.date_range})"


@dataclass
class Fact:
    kind: FactKind
    value: str
    experience_id: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        self.kind = FactKind(self.kind)
        self.value = self.value.strip()


@dataclass
class Experience:
    """The canonical record of something that happened. Facts only, no framing."""

    job_id: int
    summary: str
    facts: list[Fact] = field(default_factory=list)
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def display_id(self) -> str:
        return f"EXP-{self.id:03d}" if self.id is not None else "EXP-???"

    def facts_of(self, kind: FactKind) -> list[str]:
        return [f.value for f in self.facts if f.kind == kind]


@dataclass
class Telling:
    """One framing of an experience, for one angle. Regenerable."""

    experience_id: int
    text: str
    angle: str
    id: int | None = None
    created_at: str | None = None

    @property
    def display_id(self) -> str:
        return f"T-{self.id:03d}" if self.id is not None else "T-???"
