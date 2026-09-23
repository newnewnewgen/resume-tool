"""Load a filled requirements worksheet into the bank.

The worksheet is how requirements get answered in practice; the bank is where the
answers have to live to be reusable across applications. Without this the two
drift apart and the worksheet becomes another disposable artefact.

Idempotent: re-running after editing adds only what is new, matching the draft
ingest path.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import store
from .models import Experience, Fact, FactKind, InvalidDate, Job, validate_date


class WorksheetError(ValueError):
    """Raised when a worksheet is malformed."""


@dataclass
class LoadResult:
    jobs_created: int = 0
    jobs_existing: int = 0
    experiences_created: int = 0
    experiences_skipped: int = 0
    facts_created: int = 0

    def __str__(self) -> str:
        parts = [
            f"{self.jobs_created} job(s) created",
            f"{self.experiences_created} experience(s) created",
            f"{self.facts_created} fact(s) recorded",
        ]
        if self.jobs_existing:
            parts.append(f"{self.jobs_existing} job(s) already existed")
        if self.experiences_skipped:
            parts.append(f"{self.experiences_skipped} duplicate experience(s) skipped")
        return ", ".join(parts)


def load_worksheet(conn: sqlite3.Connection, path: Path | str) -> LoadResult:
    """Read a filled worksheet and write its jobs, experiences and facts to the bank."""
    path = Path(path)
    if not path.exists():
        raise WorksheetError(f"worksheet not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorksheetError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise WorksheetError("worksheet must be a mapping")

    jobs_by_ref = _load_jobs(conn, data.get("jobs") or [])
    result = LoadResult(
        jobs_created=sum(1 for _, created in jobs_by_ref.values() if created),
        jobs_existing=sum(1 for _, created in jobs_by_ref.values() if not created),
    )

    for index, entry in enumerate(data.get("experiences") or []):
        _load_experience(conn, entry, index, jobs_by_ref, result)

    return result


def _load_jobs(conn, raw_jobs: list[Any]) -> dict[str, tuple[Job, bool]]:
    out: dict[str, tuple[Job, bool]] = {}
    for index, entry in enumerate(raw_jobs):
        where = f"jobs[{index}]"
        if not isinstance(entry, dict):
            raise WorksheetError(f"{where} must be a mapping")

        ref = str(entry.get("ref") or "").strip()
        if not ref:
            raise WorksheetError(f"{where}.ref is required — experiences refer to it")
        for field in ("employer", "title", "start_date"):
            if not str(entry.get(field) or "").strip():
                raise WorksheetError(f"{where}.{field} is required")

        try:
            job = Job(
                employer=str(entry["employer"]).strip(),
                title=str(entry["title"]).strip(),
                start_date=str(entry["start_date"]).strip(),
                end_date=str(entry.get("end_date") or "").strip() or None,
                location=str(entry.get("location") or "").strip() or None,
            )
        except InvalidDate as exc:
            raise WorksheetError(f"{where}: {exc}") from exc

        existed = store.find_job(conn, job.employer, job.title, job.start_date) is not None
        out[ref] = (store.add_job(conn, job), not existed)
    return out


def _load_experience(conn, entry: Any, index: int, jobs_by_ref, result: LoadResult) -> None:
    where = f"experiences[{index}]"
    if not isinstance(entry, dict):
        raise WorksheetError(f"{where} must be a mapping")

    job_ref = str(entry.get("job") or "").strip()
    if job_ref not in jobs_by_ref:
        known = ", ".join(sorted(jobs_by_ref)) or "none"
        raise WorksheetError(f"{where}.job={job_ref!r} does not match a job ref (have: {known})")

    summary = " ".join(str(entry.get("summary") or "").split())
    if not summary:
        raise WorksheetError(f"{where}.summary is required")

    job = jobs_by_ref[job_ref][0]
    if store.find_experience_by_summary(conn, job.id, summary) is not None:
        result.experiences_skipped += 1
        return

    facts = []
    for k, raw in enumerate(entry.get("facts") or []):
        spot = f"{where}.facts[{k}]"
        if not isinstance(raw, dict):
            raise WorksheetError(f"{spot} must be a mapping with 'kind' and 'value'")
        value = str(raw.get("value") or "").strip()
        if not value:
            raise WorksheetError(f"{spot}.value is required")
        try:
            kind = FactKind(str(raw.get("kind") or "").strip())
        except ValueError:
            valid = ", ".join(k.value for k in FactKind)
            raise WorksheetError(
                f"{spot}.kind={raw.get('kind')!r} is invalid — use one of: {valid}"
            ) from None
        facts.append(Fact(kind=kind, value=value))

    store.add_experience(conn, Experience(job_id=job.id, summary=summary, facts=facts))
    result.experiences_created += 1
    result.facts_created += len(facts)
