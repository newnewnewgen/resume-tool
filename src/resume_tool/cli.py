"""Command-line interface."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

import typer

from . import store
from .config import Config
from .db import open_db, schema_version
from .ingest import (
    DraftError,
    UnsupportedFormat,
    commit_draft,
    extract_text,
    parse_resume,
    write_draft,
)
from .models import Experience, Fact, FactKind, InvalidDate, Job

app = typer.Typer(
    help="Personal resume tool — match experience to job descriptions, surface gaps.",
    no_args_is_help=True,
    add_completion=False,
)

DbOption = Annotated[
    Path | None,
    typer.Option("--db", help="Database path. Defaults to $RESUME_TOOL_DB or ~/.resume-tool/bank.db"),
]


def _open(db: Path | None) -> sqlite3.Connection:
    return open_db(Config.load(db).db_path)


def _fail(message: str) -> None:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _resolve_experience_id(raw: str) -> int:
    """Accept either '12' or 'EXP-012'."""
    text = raw.strip().upper().removeprefix("EXP-")
    try:
        return int(text)
    except ValueError:
        _fail(f"invalid experience id: {raw!r} (expected '12' or 'EXP-012')")
        raise  # unreachable; keeps type checkers happy


# ── Setup ───────────────────────────────────────────────────────────────────


@app.command()
def init(db: DbOption = None) -> None:
    """Create the database."""
    path = Config.load(db).db_path
    existed = path.exists()
    conn = open_db(path)
    version = schema_version(conn)
    conn.close()

    verb = "Already initialized" if existed else "Initialized"
    typer.secho(f"{verb}: {path} (schema v{version})", fg=typer.colors.GREEN)


# ── Ingest ──────────────────────────────────────────────────────────────────


@app.command()
def ingest(
    resume: Annotated[Path, typer.Argument(help="Resume file (.pdf, .docx, .txt, .md)")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Where to write the draft")] = Path("draft.yaml"),
) -> None:
    """Parse a resume into a reviewable draft. Does not touch the database."""
    try:
        text = extract_text(resume)
    except (FileNotFoundError, UnsupportedFormat) as exc:
        _fail(str(exc))
        return

    result = parse_resume(text)
    if not result.jobs:
        for note in result.notes:
            typer.secho(f"  ! {note}", fg=typer.colors.YELLOW)
        _fail("no jobs found — see notes above")
        return

    path = write_draft(result, out)

    typer.secho(
        f"Parsed {len(result.jobs)} job(s), {result.experience_count} experience(s).",
        fg=typer.colors.GREEN,
    )
    flagged = sum(1 for j in result.jobs if j.notes)
    if flagged:
        typer.secho(f"  {flagged} job(s) need review — see notes in the draft.", fg=typer.colors.YELLOW)
    for note in result.notes:
        typer.secho(f"  ! {note}", fg=typer.colors.YELLOW)

    typer.echo(f"\nDraft written to {path}")
    typer.echo(f"Review and edit it, then:  resume commit {path}")


@app.command()
def commit(
    draft: Annotated[Path, typer.Argument(help="Draft file to import")] = Path("draft.yaml"),
    db: DbOption = None,
) -> None:
    """Validate a reviewed draft and write it to the database."""
    conn = _open(db)
    try:
        result = commit_draft(conn, draft)
    except DraftError as exc:
        _fail(str(exc))
        return
    finally:
        conn.close()
    typer.secho(str(result), fg=typer.colors.GREEN)


# ── Manual entry ────────────────────────────────────────────────────────────


@app.command("add-job")
def add_job(
    employer: Annotated[str, typer.Option(prompt=True)],
    title: Annotated[str, typer.Option(prompt=True)],
    start: Annotated[str, typer.Option(prompt="Start date (YYYY or YYYY-MM)")],
    end: Annotated[str, typer.Option(prompt="End date (blank if current)")] = "",
    location: Annotated[str, typer.Option(prompt="Location (optional)")] = "",
    db: DbOption = None,
) -> None:
    """Add a job by hand."""
    conn = _open(db)
    try:
        job = store.add_job(
            conn,
            Job(
                employer=employer.strip(),
                title=title.strip(),
                start_date=start.strip(),
                end_date=end.strip() or None,
                location=location.strip() or None,
            ),
        )
    except InvalidDate as exc:
        _fail(str(exc))
        return
    finally:
        conn.close()
    typer.secho(f"{job.display_id}  {job}", fg=typer.colors.GREEN)


@app.command("add-experience")
def add_experience(
    job_id: Annotated[int, typer.Option("--job", prompt="Job id")],
    summary: Annotated[str, typer.Option(prompt="What happened (facts, not framing)")],
    db: DbOption = None,
) -> None:
    """Add an experience by hand. Record what happened — framing comes later."""
    conn = _open(db)
    try:
        store.get_job(conn, job_id)
    except store.NotFound as exc:
        conn.close()
        _fail(str(exc))
        return

    experience = store.add_experience(
        conn, Experience(job_id=job_id, summary=summary.strip())
    )
    conn.close()
    typer.secho(f"{experience.display_id} created", fg=typer.colors.GREEN)


@app.command("add-fact")
def add_fact(
    experience: Annotated[str, typer.Argument(help="Experience id, e.g. 12 or EXP-012")],
    kind: Annotated[str, typer.Option(prompt=f"Kind ({', '.join(k.value for k in FactKind)})")],
    value: Annotated[str, typer.Option(prompt="Value")],
    db: DbOption = None,
) -> None:
    """Attach a structured fact to an experience."""
    experience_id = _resolve_experience_id(experience)
    try:
        fact_kind = FactKind(kind.strip().lower())
    except ValueError:
        _fail(f"invalid kind {kind!r} — use one of: {', '.join(k.value for k in FactKind)}")
        return

    conn = _open(db)
    try:
        store.get_experience(conn, experience_id)
        store.add_fact(conn, experience_id, Fact(kind=fact_kind, value=value.strip()))
    except store.NotFound as exc:
        _fail(str(exc))
        return
    finally:
        conn.close()
    typer.secho(f"Added {fact_kind} to EXP-{experience_id:03d}", fg=typer.colors.GREEN)


# ── Inspection ──────────────────────────────────────────────────────────────


@app.command()
def jobs(db: DbOption = None) -> None:
    """List jobs, most recent first."""
    conn = _open(db)
    all_jobs = store.list_jobs(conn)
    counts = {j.id: len(store.list_experiences(conn, j.id)) for j in all_jobs}
    conn.close()

    if not all_jobs:
        typer.echo("No jobs yet. Run `resume ingest <resume>` or `resume add-job`.")
        return

    for job in all_jobs:
        typer.echo(
            f"{job.display_id}  {job.title} @ {job.employer}"
            f"  [{job.date_range}]  {counts[job.id]} experience(s)"
        )


@app.command()
def experiences(
    job: Annotated[int | None, typer.Option("--job", help="Filter by job id")] = None,
    db: DbOption = None,
) -> None:
    """List experiences."""
    conn = _open(db)
    items = store.list_experiences(conn, job)
    jobs_by_id = {j.id: j for j in store.list_jobs(conn)}
    conn.close()

    if not items:
        typer.echo("No experiences yet.")
        return

    for experience in items:
        parent = jobs_by_id.get(experience.job_id)
        where = f"{parent.employer}" if parent else f"job {experience.job_id}"
        summary = experience.summary
        if len(summary) > 88:
            summary = summary[:85] + "..."
        typer.echo(f"{experience.display_id}  [{where}]  {summary}")


@app.command()
def show(
    experience: Annotated[str, typer.Argument(help="Experience id, e.g. 12 or EXP-012")],
    db: DbOption = None,
) -> None:
    """Show one experience in full, with its facts and tellings."""
    experience_id = _resolve_experience_id(experience)
    conn = _open(db)
    try:
        item = store.get_experience(conn, experience_id)
        parent = store.get_job(conn, item.job_id)
        tellings = store.tellings_for(conn, experience_id)
    except store.NotFound as exc:
        _fail(str(exc))
        return
    finally:
        conn.close()

    typer.secho(f"{item.display_id}", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Job:     {parent.title} @ {parent.employer} [{parent.date_range}]")
    typer.echo(f"  Summary: {item.summary}")

    if item.facts:
        typer.echo("  Facts:")
        for kind in FactKind:
            values = item.facts_of(kind)
            if values:
                typer.echo(f"    {kind.value:13} {', '.join(values)}")
    else:
        typer.echo("  Facts:   (none)")

    typer.echo(f"  Tellings: {len(tellings)}")
    for telling in tellings:
        typer.echo(f"    {telling.display_id} [{telling.angle}] {telling.text}")


@app.command()
def stats(db: DbOption = None) -> None:
    """Show what is in the bank."""
    conn = _open(db)
    counts = store.stats(conn)
    conn.close()
    for label, value in counts.items():
        typer.echo(f"{label:14} {value}")


if __name__ == "__main__":
    app()
