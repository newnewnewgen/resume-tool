"""Repository layer. All SQL lives here."""

from __future__ import annotations

import sqlite3

from .models import Experience, Fact, FactKind, Job, Telling, date_sort_key


class NotFound(LookupError):
    """Raised when a lookup by id finds nothing."""


# ── Jobs ────────────────────────────────────────────────────────────────────


def add_job(conn: sqlite3.Connection, job: Job) -> Job:
    """Insert a job, or return the existing one if it already matches."""
    existing = find_job(conn, job.employer, job.title, job.start_date)
    if existing is not None:
        return existing

    cur = conn.execute(
        "INSERT INTO job (employer, title, start_date, end_date, location) "
        "VALUES (?, ?, ?, ?, ?)",
        (job.employer, job.title, job.start_date, job.end_date, job.location),
    )
    conn.commit()
    job.id = cur.lastrowid
    return job


def find_job(
    conn: sqlite3.Connection, employer: str, title: str, start_date: str
) -> Job | None:
    row = conn.execute(
        "SELECT * FROM job WHERE employer = ? AND title = ? AND start_date = ?",
        (employer, title, start_date),
    ).fetchone()
    return _job_from_row(row) if row else None


def get_job(conn: sqlite3.Connection, job_id: int) -> Job:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise NotFound(f"no job with id {job_id}")
    return _job_from_row(row)


def list_jobs(conn: sqlite3.Connection) -> list[Job]:
    """All jobs, most recent first."""
    rows = conn.execute("SELECT * FROM job").fetchall()
    jobs = [_job_from_row(r) for r in rows]
    return sorted(jobs, key=lambda j: date_sort_key(j.end_date), reverse=True)


def _job_from_row(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        employer=row["employer"],
        title=row["title"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        location=row["location"],
    )


# ── Experiences ─────────────────────────────────────────────────────────────


def add_experience(conn: sqlite3.Connection, experience: Experience) -> Experience:
    """Insert an experience and its facts in one transaction."""
    with conn:
        cur = conn.execute(
            "INSERT INTO experience (job_id, summary) VALUES (?, ?)",
            (experience.job_id, experience.summary),
        )
        experience.id = cur.lastrowid
        for fact in experience.facts:
            fact.experience_id = experience.id
            conn.execute(
                "INSERT OR IGNORE INTO experience_fact (experience_id, kind, value) "
                "VALUES (?, ?, ?)",
                (experience.id, str(fact.kind), fact.value),
            )
    return get_experience(conn, experience.id)


def find_experience_by_summary(
    conn: sqlite3.Connection, job_id: int, summary: str
) -> Experience | None:
    """Exact-summary lookup within a job.

    Guards against re-importing the same draft. This is not the semantic dedup that
    blocker 2 needs — that requires embeddings and lands later. This only catches
    byte-identical re-imports, which is a data-integrity concern, not a matching one.
    """
    row = conn.execute(
        "SELECT * FROM experience WHERE job_id = ? AND summary = ?",
        (job_id, summary.strip()),
    ).fetchone()
    return _experience_from_row(conn, row) if row else None


def get_experience(conn: sqlite3.Connection, experience_id: int) -> Experience:
    row = conn.execute(
        "SELECT * FROM experience WHERE id = ?", (experience_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"no experience with id {experience_id}")
    return _experience_from_row(conn, row)


def list_experiences(
    conn: sqlite3.Connection, job_id: int | None = None
) -> list[Experience]:
    if job_id is None:
        rows = conn.execute("SELECT * FROM experience ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM experience WHERE job_id = ? ORDER BY id", (job_id,)
        ).fetchall()
    return [_experience_from_row(conn, r) for r in rows]


def update_summary(conn: sqlite3.Connection, experience_id: int, summary: str) -> None:
    """Correct the facts of an existing experience (write-classification case 3)."""
    with conn:
        cur = conn.execute(
            "UPDATE experience SET summary = ?, updated_at = datetime('now') WHERE id = ?",
            (summary, experience_id),
        )
    if cur.rowcount == 0:
        raise NotFound(f"no experience with id {experience_id}")


def delete_experience(conn: sqlite3.Connection, experience_id: int) -> None:
    with conn:
        cur = conn.execute("DELETE FROM experience WHERE id = ?", (experience_id,))
    if cur.rowcount == 0:
        raise NotFound(f"no experience with id {experience_id}")


def _experience_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Experience:
    return Experience(
        id=row["id"],
        job_id=row["job_id"],
        summary=row["summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        facts=facts_for(conn, row["id"]),
    )


# ── Facts ───────────────────────────────────────────────────────────────────


def add_fact(conn: sqlite3.Connection, experience_id: int, fact: Fact) -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO experience_fact (experience_id, kind, value) "
            "VALUES (?, ?, ?)",
            (experience_id, str(fact.kind), fact.value),
        )


def facts_for(conn: sqlite3.Connection, experience_id: int) -> list[Fact]:
    rows = conn.execute(
        "SELECT * FROM experience_fact WHERE experience_id = ? ORDER BY kind, value",
        (experience_id,),
    ).fetchall()
    return [
        Fact(
            id=r["id"],
            experience_id=r["experience_id"],
            kind=FactKind(r["kind"]),
            value=r["value"],
        )
        for r in rows
    ]


# ── Tellings ────────────────────────────────────────────────────────────────


def add_telling(conn: sqlite3.Connection, telling: Telling) -> Telling:
    with conn:
        cur = conn.execute(
            "INSERT INTO telling (experience_id, text, angle) VALUES (?, ?, ?)",
            (telling.experience_id, telling.text, telling.angle),
        )
    telling.id = cur.lastrowid
    return telling


def tellings_for(conn: sqlite3.Connection, experience_id: int) -> list[Telling]:
    rows = conn.execute(
        "SELECT * FROM telling WHERE experience_id = ? ORDER BY id", (experience_id,)
    ).fetchall()
    return [
        Telling(
            id=r["id"],
            experience_id=r["experience_id"],
            text=r["text"],
            angle=r["angle"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ── Summary ─────────────────────────────────────────────────────────────────


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def count(table: str) -> int:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

    return {
        "jobs": count("job"),
        "experiences": count("experience"),
        "facts": count("experience_fact"),
        "tellings": count("telling"),
        "applications": count("application"),
    }
