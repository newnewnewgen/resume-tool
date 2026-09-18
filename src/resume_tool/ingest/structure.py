"""Text → candidate jobs and experiences. Deterministic, no LLM.

This is heuristic and will be imperfect on unusual layouts. That is by design: the
output is a draft the user reviews and corrects before it reaches the database.
Anything uncertain is flagged in `notes` rather than silently guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Date detection ──────────────────────────────────────────────────────────

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(_MONTHS)

_MONTH_YEAR = rf"(?:{_MONTH_ALT})[a-z]*\.?\s*,?\s*\d{{4}}"
_NUM_YEAR = r"\d{1,2}[/-]\d{4}"
_BARE_YEAR = r"\d{4}"
_POINT = rf"(?:{_MONTH_YEAR}|{_NUM_YEAR}|{_BARE_YEAR})"
_PRESENT = r"present|current|now|ongoing|today"
_SEP = r"\s*(?:[-–—]{1,2}|to|through|until)\s*"

DATE_RANGE = re.compile(rf"({_POINT}){_SEP}({_POINT}|{_PRESENT})", re.IGNORECASE)

# ── Structure markers ───────────────────────────────────────────────────────

_BULLET_CHARS = "•●○▪◦‣·∙-–—*"
BULLET_LINE = re.compile(rf"^\s*[{re.escape(_BULLET_CHARS)}]\s+(?P<body>.+)$")
NUMBERED_LINE = re.compile(r"^\s*\d{1,2}[.)]\s+(?P<body>.+)$")

_EXPERIENCE_SECTIONS = {
    "experience", "work experience", "professional experience", "employment",
    "employment history", "work history", "career history", "relevant experience",
}
_OTHER_SECTIONS = {
    "education", "skills", "technical skills", "projects", "certifications",
    "awards", "summary", "objective", "publications", "interests", "references",
    "volunteer", "languages", "activities",
}
_SECTION_NAMES = _EXPERIENCE_SECTIONS | _OTHER_SECTIONS

_ROLE_WORDS = {
    "engineer", "developer", "manager", "director", "analyst", "lead", "architect",
    "designer", "consultant", "specialist", "coordinator", "associate", "intern",
    "scientist", "administrator", "officer", "president", "founder", "head",
    "supervisor", "technician", "strategist", "producer", "writer", "researcher",
}
_ORG_WORDS = {
    "inc", "inc.", "llc", "ltd", "ltd.", "corp", "corp.", "corporation", "company",
    "co", "co.", "group", "labs", "technologies", "systems", "solutions", "partners",
    "university", "institute", "foundation", "agency", "studio", "gmbh", "plc",
}

_SPLIT_SEPARATORS = re.compile(r"\s*(?:\||·|—|–|•|\t|,\s+|\s+at\s+|\s{3,})\s*")


# ── Output shapes ───────────────────────────────────────────────────────────


@dataclass
class CandidateExperience:
    summary: str


@dataclass
class CandidateJob:
    employer: str
    title: str
    start_date: str | None
    end_date: str | None
    location: str | None = None
    experiences: list[CandidateExperience] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_header: str = ""


@dataclass
class ParseResult:
    jobs: list[CandidateJob] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def experience_count(self) -> int:
        return sum(len(j.experiences) for j in self.jobs)


# ── Date helpers ────────────────────────────────────────────────────────────


def normalize_date(raw: str) -> str | None:
    """Normalize a date fragment to 'YYYY' or 'YYYY-MM'. None for present/unparseable."""
    text = raw.strip().lower().rstrip(".,")
    if re.fullmatch(_PRESENT, text, re.IGNORECASE):
        return None

    if m := re.match(rf"({_MONTH_ALT})[a-z]*\.?\s*,?\s*(\d{{4}})", text):
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"

    if m := re.match(r"(\d{1,2})[/-](\d{4})", text):
        month = int(m.group(1))
        if 1 <= month <= 12:
            return f"{m.group(2)}-{month:02d}"
        return m.group(2)

    if m := re.match(r"(\d{4})", text):
        return m.group(1)

    return None


def find_date_range(line: str) -> tuple[str | None, str | None, re.Match] | None:
    """Find a date range in a line. Returns (start, end, match) or None."""
    match = DATE_RANGE.search(line)
    if match is None:
        return None
    return normalize_date(match.group(1)), normalize_date(match.group(2)), match


# ── Parsing ─────────────────────────────────────────────────────────────────


def parse_resume(text: str) -> ParseResult:
    """Parse resume text into candidate jobs and experiences."""
    lines = _clean_lines(text)
    result = ParseResult()
    if not lines:
        result.notes.append("No text content found.")
        return result

    in_experience_section, saw_section = _section_map(lines)

    # Job headers are lines carrying a date range, inside an experience section
    # (or anywhere, if the resume has no recognizable section headers).
    header_indices = [
        i
        for i, line in enumerate(lines)
        if find_date_range(line) is not None
        and (in_experience_section[i] or not saw_section)
        and not _is_bullet(line)
    ]

    if not header_indices:
        result.notes.append(
            "No date ranges found — could not identify job boundaries. "
            "Add jobs manually with `resume add-job`."
        )
        return result

    for n, start in enumerate(header_indices):
        end = header_indices[n + 1] if n + 1 < len(header_indices) else len(lines)
        block = lines[start:end]
        prev_line = lines[start - 1] if start > 0 else None
        job = _parse_job_block(block, prev_line)
        if job is not None:
            result.jobs.append(job)

    if not saw_section:
        result.notes.append(
            "No section headers recognized; every dated line was treated as a job. "
            "Check for education entries parsed as jobs."
        )
    return result


def _parse_job_block(block: list[str], prev_line: str | None) -> CandidateJob | None:
    header = block[0]
    found = find_date_range(header)
    if found is None:
        return None
    start_date, end_date, match = found

    notes: list[str] = []
    remainder = (header[: match.start()] + " " + header[match.end() :]).strip()
    remainder = remainder.strip("|·—–,-– \t")

    body_start = 1
    if not remainder:
        # The dated line held only dates; the name is on an adjacent line.
        if len(block) > 1 and not _is_bullet(block[1]):
            remainder = block[1]
            body_start = 2
        elif prev_line and not _is_bullet(prev_line):
            remainder = prev_line
        notes.append("Employer/title taken from an adjacent line — verify.")

    employer, title, location = _split_header(remainder)
    if not employer or not title:
        notes.append("Could not separate employer from title — verify.")

    experiences = _extract_experiences(block[body_start:])
    if not experiences:
        notes.append("No bullet points found for this job.")

    return CandidateJob(
        employer=employer or "UNKNOWN",
        title=title or "UNKNOWN",
        start_date=start_date,
        end_date=end_date,
        location=location,
        experiences=experiences,
        notes=notes,
        raw_header=header,
    )


def _split_header(text: str) -> tuple[str, str, str | None]:
    """Split a header into (employer, title, location). Best effort."""
    if not text:
        return "", "", None

    parts = [p.strip(" |·—–,\t") for p in _SPLIT_SEPARATORS.split(text)]
    parts = [p for p in parts if p]
    if not parts:
        return "", "", None
    if len(parts) == 1:
        return "", parts[0], None

    location = None
    if len(parts) > 2 and _looks_like_location(parts[-1]):
        location = parts.pop()

    title_idx = next((i for i, p in enumerate(parts) if _looks_like_role(p)), None)
    org_idx = next((i for i, p in enumerate(parts) if _looks_like_org(p)), None)

    if title_idx is not None and org_idx is not None and title_idx != org_idx:
        return parts[org_idx], parts[title_idx], location
    if title_idx is not None:
        other = next((p for i, p in enumerate(parts) if i != title_idx), "")
        return other, parts[title_idx], location
    if org_idx is not None:
        other = next((p for i, p in enumerate(parts) if i != org_idx), "")
        return parts[org_idx], other, location

    # No signal either way — assume "Title | Employer", the most common layout.
    return parts[1], parts[0], location


def _extract_experiences(lines: list[str]) -> list[CandidateExperience]:
    """Pull bullets out of a job block, joining wrapped continuation lines."""
    experiences: list[CandidateExperience] = []
    current: str | None = None

    for line in lines:
        body = _bullet_body(line)
        if body is not None:
            if current:
                experiences.append(CandidateExperience(summary=_tidy(current)))
            current = body
        elif current is not None and _is_continuation(line):
            current = f"{current} {line.strip()}"
        elif current:
            experiences.append(CandidateExperience(summary=_tidy(current)))
            current = None

    if current:
        experiences.append(CandidateExperience(summary=_tidy(current)))
    return [e for e in experiences if len(e.summary) > 10]


# ── Small predicates ────────────────────────────────────────────────────────


def _clean_lines(text: str) -> list[str]:
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.replace("\xa0", " ").rstrip()
        if line.strip():
            out.append(line)
    return out


def _section_map(lines: list[str]) -> tuple[list[bool], bool]:
    """Mark which lines sit inside an experience section. Returns (flags, saw_any)."""
    flags: list[bool] = []
    saw_section = False
    inside = False
    for line in lines:
        name = _section_name(line)
        if name is not None:
            saw_section = True
            inside = name in _EXPERIENCE_SECTIONS
            flags.append(False)
            continue
        flags.append(inside)
    return flags, saw_section


def _section_name(line: str) -> str | None:
    """Return the canonical section name if this line is a section header."""
    stripped = line.strip().strip(":").strip()
    if len(stripped) > 40 or _is_bullet(line):
        return None
    normalized = re.sub(r"[^a-z ]", "", stripped.lower()).strip()
    return normalized if normalized in _SECTION_NAMES else None


def _is_bullet(line: str) -> bool:
    return _bullet_body(line) is not None


def _bullet_body(line: str) -> str | None:
    if m := BULLET_LINE.match(line):
        return m.group("body").strip()
    if m := NUMBERED_LINE.match(line):
        return m.group("body").strip()
    return None


def _is_continuation(line: str) -> bool:
    """A wrapped line: indented or starting lowercase, and not a new section."""
    if _section_name(line) is not None:
        return False
    if find_date_range(line) is not None:
        return False
    stripped = line.strip()
    return bool(stripped) and (line.startswith((" ", "\t")) or stripped[0].islower())


def _looks_like_role(text: str) -> bool:
    words = set(re.findall(r"[a-z]+", text.lower()))
    return bool(words & _ROLE_WORDS)


def _looks_like_org(text: str) -> bool:
    words = set(re.findall(r"[a-z.]+", text.lower()))
    return bool(words & _ORG_WORDS)


def _looks_like_location(text: str) -> bool:
    if re.search(r",\s*[A-Z]{2}$", text.strip()):
        return True
    return bool(re.fullmatch(r"(remote|hybrid|on-?site)", text.strip(), re.IGNORECASE))


def _tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(";,")
