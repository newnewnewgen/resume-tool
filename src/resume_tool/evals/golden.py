"""Load a golden set: a self-contained bank plus cases with known answers.

The file carries its own jobs and experiences so the eval is hermetic — it
never reads the user's real bank, and the committed set stays synthetic
because this repository is public. A private golden set built from real
history belongs in evals/private/ or under a *.filled.* name, both gitignored.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .. import store
from ..models import Experience, Fact, FactKind, InvalidDate, Job, Tier


class GoldenError(ValueError):
    """Raised when a golden set file is malformed."""


@dataclass
class BankExperience:
    ref: str
    job_ref: str
    summary: str
    facts: list[Fact] = field(default_factory=list)


@dataclass
class GoldenCase:
    id: str
    requirement: str
    tier: Tier
    expect: list[str]  # experience refs; empty = this requirement is a gap
    note: str | None = None

    @property
    def expects_gap(self) -> bool:
        return not self.expect


@dataclass
class GoldenSet:
    path: Path
    jobs: dict[str, Job]  # ref → unsaved Job
    experiences: list[BankExperience]
    cases: list[GoldenCase]


def load_golden(path: Path | str) -> GoldenSet:
    path = Path(path)
    if not path.exists():
        raise GoldenError(f"golden set not found: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GoldenError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GoldenError("golden set must be a mapping")

    jobs = _parse_jobs(data.get("jobs") or [])
    experiences = _parse_experiences(data.get("experiences") or [], jobs)
    cases = _parse_cases(data.get("cases") or [], experiences)
    if not cases:
        raise GoldenError("golden set has no cases")
    return GoldenSet(path=path, jobs=jobs, experiences=experiences, cases=cases)


def build_bank(conn: sqlite3.Connection, golden: GoldenSet) -> dict[str, int]:
    """Write the golden bank into a (fresh) database. Returns ref → experience id."""
    job_ids: dict[str, int] = {}
    for ref, job in golden.jobs.items():
        job_ids[ref] = store.add_job(conn, job).id

    ids_by_ref: dict[str, int] = {}
    for entry in golden.experiences:
        experience = store.add_experience(
            conn,
            Experience(
                job_id=job_ids[entry.job_ref],
                summary=entry.summary,
                facts=[Fact(kind=f.kind, value=f.value) for f in entry.facts],
            ),
        )
        ids_by_ref[entry.ref] = experience.id
    return ids_by_ref


def _parse_jobs(raw: list[Any]) -> dict[str, Job]:
    jobs: dict[str, Job] = {}
    for index, entry in enumerate(raw):
        where = f"jobs[{index}]"
        if not isinstance(entry, dict):
            raise GoldenError(f"{where} must be a mapping")
        ref = str(entry.get("ref") or "").strip()
        if not ref:
            raise GoldenError(f"{where}.ref is required")
        if ref in jobs:
            raise GoldenError(f"duplicate job ref {ref!r}")
        for name in ("employer", "title", "start_date"):
            if not str(entry.get(name) or "").strip():
                raise GoldenError(f"{where}.{name} is required")
        try:
            jobs[ref] = Job(
                employer=str(entry["employer"]).strip(),
                title=str(entry["title"]).strip(),
                start_date=str(entry["start_date"]).strip(),
                end_date=str(entry.get("end_date") or "").strip() or None,
                location=str(entry.get("location") or "").strip() or None,
            )
        except InvalidDate as exc:
            raise GoldenError(f"{where}: {exc}") from exc
    if not jobs:
        raise GoldenError("golden set has no jobs")
    return jobs


def _parse_experiences(raw: list[Any], jobs: dict[str, Job]) -> list[BankExperience]:
    out: list[BankExperience] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"experiences[{index}]"
        if not isinstance(entry, dict):
            raise GoldenError(f"{where} must be a mapping")

        ref = str(entry.get("ref") or "").strip()
        if not ref:
            raise GoldenError(f"{where}.ref is required — cases refer to it")
        if ref in seen:
            raise GoldenError(f"duplicate experience ref {ref!r}")
        seen.add(ref)

        job_ref = str(entry.get("job") or "").strip()
        if job_ref not in jobs:
            known = ", ".join(sorted(jobs)) or "none"
            raise GoldenError(f"{where}.job={job_ref!r} does not match a job ref (have: {known})")

        summary = " ".join(str(entry.get("summary") or "").split())
        if not summary:
            raise GoldenError(f"{where}.summary is required")

        facts = []
        for k, raw_fact in enumerate(entry.get("facts") or []):
            spot = f"{where}.facts[{k}]"
            if not isinstance(raw_fact, dict):
                raise GoldenError(f"{spot} must be a mapping with 'kind' and 'value'")
            value = str(raw_fact.get("value") or "").strip()
            if not value:
                raise GoldenError(f"{spot}.value is required")
            try:
                kind = FactKind(str(raw_fact.get("kind") or "").strip())
            except ValueError:
                valid = ", ".join(k.value for k in FactKind)
                raise GoldenError(
                    f"{spot}.kind={raw_fact.get('kind')!r} is invalid — use one of: {valid}"
                ) from None
            facts.append(Fact(kind=kind, value=value))

        out.append(BankExperience(ref=ref, job_ref=job_ref, summary=summary, facts=facts))
    if not out:
        raise GoldenError("golden set has no experiences")
    return out


def _parse_cases(raw: list[Any], experiences: list[BankExperience]) -> list[GoldenCase]:
    known_refs = {e.ref for e in experiences}
    out: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(raw):
        where = f"cases[{index}]"
        if not isinstance(entry, dict):
            raise GoldenError(f"{where} must be a mapping")

        case_id = str(entry.get("id") or "").strip()
        if not case_id:
            raise GoldenError(f"{where}.id is required")
        if case_id in seen_ids:
            raise GoldenError(f"duplicate case id {case_id!r}")
        seen_ids.add(case_id)

        requirement = " ".join(str(entry.get("requirement") or "").split())
        if not requirement:
            raise GoldenError(f"{where}.requirement is required")

        try:
            tier = Tier(str(entry.get("tier") or "").strip())
        except ValueError:
            valid = ", ".join(t.value for t in Tier)
            raise GoldenError(
                f"{where}.tier={entry.get('tier')!r} is invalid — use one of: {valid}"
            ) from None

        raw_expect = entry.get("expect")
        if raw_expect in ("gap", None, []):
            expect: list[str] = []
        elif isinstance(raw_expect, str):
            expect = [raw_expect.strip()]
        elif isinstance(raw_expect, list):
            expect = [str(r).strip() for r in raw_expect]
        else:
            raise GoldenError(f"{where}.expect must be 'gap', a ref, or a list of refs")
        for ref in expect:
            if ref not in known_refs:
                raise GoldenError(f"{where}.expect names unknown experience ref {ref!r}")

        note = str(entry.get("note") or "").strip() or None
        out.append(
            GoldenCase(id=case_id, requirement=requirement, tier=tier, expect=expect, note=note)
        )
    return out
