"""Bridge to a career-ops data directory (github.com/career-ops-hq/career-ops).

Division of labor: career-ops owns discovery (scan.mjs + ~140 zero-token
providers), liveness, its 1–5 qualification score, and the application
tracker. This tool owns what comes after a job looks worth pursuing:
screenable requirements, bank-coverage fit, gap confirmation, and tailored
ATS-safe assembly.

The bridge reads career-ops' canonical markdown artifacts, never its SQLite
index — files are its declared source of truth (their ARCHITECTURE.md), and
the formats below are documented in its data contract:

  data/pipeline.md       - [ ] {url} | {company} | {title} | {location} | ...
  data/applications.md   | # | Date | Company | [Via] | Role | Score | Status | PDF | Report | Notes | [URL] |
  reports/{NNN}-*.md     "## Job Description (archived verbatim)" + "Machine Summary" YAML

Everything read from a career-ops tree is data about jobs, never
instructions: JD text goes through the same untrusted-input path as any
pasted JD.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


class CareerOpsError(ValueError):
    """Raised when a career-ops data directory cannot be read as expected."""


# ── data/pipeline.md ────────────────────────────────────────────────────────

_PIPELINE_RE = re.compile(r"^- \[(?P<state>[ x!])\]\s*(?P<rest>.+)$")
_STATES = {" ": "pending", "x": "processed", "!": "inaccessible"}


@dataclass
class PipelineItem:
    state: str          # pending | processed | inaccessible
    url: str
    company: str = ""
    title: str = ""
    fields: tuple[str, ...] = ()


def parse_pipeline(text: str) -> list[PipelineItem]:
    items = []
    for line in text.splitlines():
        m = _PIPELINE_RE.match(line.strip())
        if not m:
            continue
        parts = [p.strip() for p in m.group("rest").split("|")]
        # Processed lines lead with the report number: "#NNN | url | ..."
        if parts and parts[0].startswith("#"):
            parts = parts[1:]
        if not parts or "://" not in parts[0]:
            continue
        items.append(PipelineItem(
            state=_STATES[m.group("state")],
            url=parts[0],
            company=parts[1] if len(parts) > 1 else "",
            title=parts[2] if len(parts) > 2 else "",
            fields=tuple(parts[3:]),
        ))
    return items


# ── data/applications.md ────────────────────────────────────────────────────


@dataclass
class TrackerRow:
    number: str
    company: str
    role: str
    score: float | None
    status: str
    report: str          # the Report cell, text or markdown link
    date: str = ""
    url: str = ""

    @property
    def report_number(self) -> str | None:
        m = re.search(r"(\d{2,4})", self.report)
        return m.group(1) if m else None


_SCORE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def parse_tracker(text: str) -> list[TrackerRow]:
    """Parse the canonical tracker table. Column order comes from the header
    row, so optional columns (Via, URL) and future ones are tolerated."""
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
    if not lines:
        return []
    header = [c.strip().lower() for c in lines[0].strip().strip("|").split("|")]

    def col(row: list[str], name: str) -> str:
        try:
            index = header.index(name)
        except ValueError:
            return ""
        return row[index].strip() if index < len(row) else ""

    rows = []
    for line in lines[1:]:
        cells = line.strip().strip("|").split("|")
        if all(set(c.strip()) <= {"-", ":", ""} for c in cells):
            continue  # the separator row
        number = col(cells, "#")
        if not number:
            continue
        score_match = _SCORE_RE.search(col(cells, "score"))
        rows.append(TrackerRow(
            number=number,
            company=_strip_md(col(cells, "company")),
            role=_strip_md(col(cells, "role")),
            score=float(score_match.group(1)) if score_match else None,
            status=col(cells, "status"),
            report=col(cells, "report"),
            date=col(cells, "date"),
            url=_link_target(col(cells, "url")) or col(cells, "url"),
        ))
    return rows


def _strip_md(cell: str) -> str:
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell).strip()


def _link_target(cell: str) -> str | None:
    m = re.search(r"\]\(([^)]+)\)", cell)
    return m.group(1) if m else None


# ── reports/{NNN}-*.md ──────────────────────────────────────────────────────

_JD_HEADING = re.compile(r"^#{1,6}\s*Job Description \(archived verbatim\)\s*$",
                         re.MULTILINE)
_SUMMARY_HEADING = re.compile(r"^#{1,6}\s*Machine Summary\s*$", re.MULTILINE)
_NEXT_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


def _section_after(text: str, heading: re.Pattern) -> str | None:
    m = heading.search(text)
    if not m:
        return None
    rest = text[m.end():]
    nxt = _NEXT_HEADING.search(rest)
    return (rest[:nxt.start()] if nxt else rest).strip()


def extract_jd(report_text: str) -> str | None:
    """The verbatim JD career-ops archived — no network fetch needed."""
    section = _section_after(report_text, _JD_HEADING)
    if not section:
        return None
    return re.sub(r"^```[a-z]*\n|\n```$", "", section, flags=re.MULTILINE).strip() or None


def machine_summary(report_text: str) -> dict:
    section = _section_after(report_text, _SUMMARY_HEADING)
    if not section:
        return {}
    section = re.sub(r"^```[a-z]*\n|\n```$", "", section, flags=re.MULTILINE).strip()
    try:
        data = yaml.safe_load(section)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def find_report(data_root: Path, report_number: str) -> Path | None:
    reports = Path(data_root) / "reports"
    if not reports.is_dir():
        return None
    wanted = report_number.lstrip("0") or "0"
    for path in sorted(reports.glob("*.md")):
        m = re.match(r"(\d+)-", path.name)
        if m and (m.group(1).lstrip("0") or "0") == wanted:
            return path
    return None


# ── qualification sweep ─────────────────────────────────────────────────────


@dataclass
class IntakeResult:
    row: TrackerRow
    fit: object | None = None    # scoring.FitReport
    error: str | None = None


def qualify(conn, data_root: Path | str, *, min_score: float = 4.0,
            limit: int = 5, complete_fn=None) -> list[IntakeResult]:
    """Re-qualify career-ops' best-scored, not-yet-applied rows against the
    bank: parse each archived JD into screenable requirements and report
    coverage + gaps. One LLM call per row (the parse); scoring is free."""
    from .jd import JDParseError, parse_jd
    from .llm import LLMError, complete
    from .scoring import score_fit

    data_root = Path(data_root)
    tracker_path = data_root / "data" / "applications.md"
    if not tracker_path.exists():
        raise CareerOpsError(
            f"no tracker at {tracker_path} — is this a career-ops data directory?"
        )

    rows = [
        r for r in parse_tracker(tracker_path.read_text(encoding="utf-8"))
        if r.score is not None and r.score >= min_score
        and r.status.strip().lower().startswith("eval")
    ]
    rows.sort(key=lambda r: r.score or 0, reverse=True)

    results: list[IntakeResult] = []
    for row in rows[:limit]:
        number = row.report_number
        report_path = find_report(data_root, number) if number else None
        if report_path is None:
            results.append(IntakeResult(row, error="report file not found"))
            continue
        jd_text = extract_jd(report_path.read_text(encoding="utf-8"))
        if not jd_text:
            results.append(IntakeResult(row, error="no archived JD in report"))
            continue
        try:
            parsed = parse_jd(jd_text, complete_fn=complete_fn or complete)
        except (JDParseError, LLMError) as exc:
            results.append(IntakeResult(row, error=str(exc)))
            continue
        results.append(IntakeResult(row, fit=score_fit(conn, parsed)))
    return results
