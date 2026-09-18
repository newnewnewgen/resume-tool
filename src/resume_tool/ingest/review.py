"""Draft round-trip: parse → editable YAML → user corrects → commit to the database.

Nothing reaches the bank without passing through a file the user can edit. Heuristic
parsing is imperfect, and the durable layer is facts — so a human confirms them once,
rather than the tool guessing repeatedly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .. import store
from ..models import Experience, Fact, FactKind, InvalidDate, Job, validate_date
from .structure import ParseResult

DRAFT_HEADER = """\
# Resume ingest draft — review before committing.
#
#   dates:     'YYYY' or 'YYYY-MM'. Leave end_date blank for a current role.
#   notes:     parser warnings. Delete them once resolved; they are not imported.
#   facts:     optional. kind must be one of
#              metric | technology | scope | collaborator | outcome
#
# Delete any job or experience you do not want imported, then:
#   resume commit <this-file>
"""


class DraftError(ValueError):
    """Raised when a draft file is malformed."""


@dataclass
class CommitResult:
    jobs_created: int = 0
    experiences_created: int = 0
    jobs_existing: int = 0
    experiences_skipped: int = 0

    def __str__(self) -> str:
        parts = [
            f"{self.jobs_created} job(s) created",
            f"{self.experiences_created} experience(s) created",
        ]
        if self.jobs_existing:
            parts.append(f"{self.jobs_existing} job(s) already existed")
        if self.experiences_skipped:
            parts.append(f"{self.experiences_skipped} duplicate experience(s) skipped")
        return ", ".join(parts)


# ── Writing ─────────────────────────────────────────────────────────────────


def to_draft(result: ParseResult) -> str:
    """Render a parse result as editable YAML."""
    jobs: list[dict[str, Any]] = []
    for job in result.jobs:
        entry: dict[str, Any] = {
            "employer": job.employer,
            "title": job.title,
            "start_date": job.start_date or "",
            "end_date": job.end_date or "",
            "location": job.location or "",
            "experiences": [
                {"summary": e.summary, "facts": []} for e in job.experiences
            ],
        }
        if job.notes:
            entry["notes"] = job.notes
        jobs.append(entry)

    document = yaml.safe_dump(
        {"jobs": jobs},
        sort_keys=False,
        allow_unicode=True,
        width=100,
        default_flow_style=False,
    )

    preamble = DRAFT_HEADER
    if result.notes:
        preamble += "#\n" + "".join(f"# ! {n}\n" for n in result.notes)
    return preamble + "\n" + document


def write_draft(result: ParseResult, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_draft(result), encoding="utf-8")
    return path


# ── Reading ─────────────────────────────────────────────────────────────────


def load_draft(path: Path | str) -> list[dict[str, Any]]:
    """Load and validate a draft file. Raises DraftError with a usable message."""
    path = Path(path)
    if not path.exists():
        raise DraftError(f"draft not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DraftError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, dict) or "jobs" not in data:
        raise DraftError("draft must be a mapping with a top-level 'jobs' key")

    jobs = data["jobs"]
    if not isinstance(jobs, list):
        raise DraftError("'jobs' must be a list")

    for index, job in enumerate(jobs):
        _validate_job(job, index)
    return jobs


def _validate_job(job: Any, index: int) -> None:
    where = f"jobs[{index}]"
    if not isinstance(job, dict):
        raise DraftError(f"{where} must be a mapping")

    for required in ("employer", "title", "start_date"):
        value = job.get(required)
        if not value or not str(value).strip():
            raise DraftError(f"{where}.{required} is required")

    try:
        validate_date(str(job["start_date"]).strip(), allow_none=False)
        if end := str(job.get("end_date") or "").strip():
            validate_date(end)
    except InvalidDate as exc:
        raise DraftError(f"{where}: {exc}") from exc

    for j, experience in enumerate(job.get("experiences") or []):
        spot = f"{where}.experiences[{j}]"
        if not isinstance(experience, dict):
            raise DraftError(f"{spot} must be a mapping")
        if not str(experience.get("summary") or "").strip():
            raise DraftError(f"{spot}.summary is required")
        for k, fact in enumerate(experience.get("facts") or []):
            _validate_fact(fact, f"{spot}.facts[{k}]")


def _validate_fact(fact: Any, where: str) -> None:
    if not isinstance(fact, dict):
        raise DraftError(f"{where} must be a mapping with 'kind' and 'value'")
    kind = str(fact.get("kind") or "").strip()
    if not str(fact.get("value") or "").strip():
        raise DraftError(f"{where}.value is required")
    try:
        FactKind(kind)
    except ValueError:
        valid = ", ".join(k.value for k in FactKind)
        raise DraftError(f"{where}.kind={kind!r} is invalid — use one of: {valid}") from None


# ── Committing ──────────────────────────────────────────────────────────────


def commit_draft(conn: sqlite3.Connection, path: Path | str) -> CommitResult:
    """Validate a draft and write it to the database."""
    jobs = load_draft(path)
    result = CommitResult()

    for entry in jobs:
        job = Job(
            employer=str(entry["employer"]).strip(),
            title=str(entry["title"]).strip(),
            start_date=str(entry["start_date"]).strip(),
            end_date=str(entry.get("end_date") or "").strip() or None,
            location=str(entry.get("location") or "").strip() or None,
        )
        existed = (
            store.find_job(conn, job.employer, job.title, job.start_date) is not None
        )
        saved = store.add_job(conn, job)
        if existed:
            result.jobs_existing += 1
        else:
            result.jobs_created += 1

        for item in entry.get("experiences") or []:
            summary = str(item["summary"]).strip()

            # Re-importing an edited draft is normal; don't silently double the bank.
            if store.find_experience_by_summary(conn, saved.id, summary) is not None:
                result.experiences_skipped += 1
                continue

            facts = [
                Fact(kind=FactKind(str(f["kind"]).strip()), value=str(f["value"]).strip())
                for f in (item.get("facts") or [])
            ]
            store.add_experience(
                conn,
                Experience(
                    job_id=saved.id,  # type: ignore[arg-type]
                    summary=summary,
                    facts=facts,
                ),
            )
            result.experiences_created += 1

    return result
