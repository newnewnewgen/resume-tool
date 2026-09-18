"""Shared fixtures."""

from __future__ import annotations

import pytest

from resume_tool.db import open_db
from resume_tool.models import Experience, Fact, FactKind, Job
from resume_tool import store


@pytest.fixture
def conn():
    """An in-memory database with the schema applied."""
    connection = open_db(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def job(conn) -> Job:
    return store.add_job(
        conn,
        Job(
            employer="Acme Corp",
            title="Senior Engineer",
            start_date="2020-01",
            end_date="2022-03",
            location="San Francisco, CA",
        ),
    )


@pytest.fixture
def experience(conn, job) -> Experience:
    return store.add_experience(
        conn,
        Experience(
            job_id=job.id,
            summary="Migrated the billing service off the monolith.",
            facts=[
                Fact(kind=FactKind.TECHNOLOGY, value="Kubernetes"),
                Fact(kind=FactKind.METRIC, value="40% latency reduction"),
            ],
        ),
    )


SAMPLE_RESUME = """\
Jane Doe
jane@example.com | 555-0100 | Seattle, WA

EXPERIENCE

Senior Engineer | Acme Corp | Jan 2020 - Mar 2022
• Migrated the billing service off the monolith, cutting p99 latency by 40%.
• Led a team of 5 engineers through a zero-downtime database migration.

Software Engineer | Globex Inc | June 2017 – December 2019
• Built an internal deployment tool adopted by 12 teams.
• Reduced CI runtime from 22 minutes to 6 minutes by parallelizing the
  test suite across runners.

EDUCATION

B.S. Computer Science, State University, 2017
"""
