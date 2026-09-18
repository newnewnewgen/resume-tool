"""Store round-trips and model validation."""

from __future__ import annotations

import pytest

from resume_tool import store
from resume_tool.models import (
    Experience,
    Fact,
    FactKind,
    InvalidDate,
    Job,
    Telling,
    date_sort_key,
    validate_date,
)


# ── Dates ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["2020", "2020-01", "1999-12"])
def test_validate_date_accepts_supported_formats(value):
    assert validate_date(value) == value


@pytest.mark.parametrize(
    "value,expected", [("2020-01-15", "2020-01"), ("1999-12-31", "1999-12")]
)
def test_validate_date_truncates_day_precision(value, expected):
    assert validate_date(value) == expected


@pytest.mark.parametrize("value", ["2020-1", "20-01", "Jan 2020", "2020-13", "", "2020/01"])
def test_validate_date_rejects_bad_input(value):
    with pytest.raises(InvalidDate):
        validate_date(value)


def test_validate_date_none_handling():
    assert validate_date(None) is None
    with pytest.raises(InvalidDate):
        validate_date(None, allow_none=False)


def test_current_role_sorts_most_recent():
    assert date_sort_key(None) > date_sort_key("2025-12")
    assert date_sort_key("2020-06") > date_sort_key("2020-05")
    assert date_sort_key("2020") < date_sort_key("2020-01")


def test_job_validates_dates_on_construction():
    with pytest.raises(InvalidDate):
        Job(employer="A", title="B", start_date="nonsense")


# ── Jobs ────────────────────────────────────────────────────────────────────


def test_add_job_round_trips(conn, job):
    fetched = store.get_job(conn, job.id)
    assert fetched.employer == "Acme Corp"
    assert fetched.title == "Senior Engineer"
    assert fetched.location == "San Francisco, CA"
    assert fetched.display_id == f"JOB-{job.id:03d}"


def test_add_job_is_idempotent(conn, job):
    again = store.add_job(
        conn, Job(employer="Acme Corp", title="Senior Engineer", start_date="2020-01")
    )
    assert again.id == job.id
    assert len(store.list_jobs(conn)) == 1


def test_list_jobs_orders_current_role_first(conn):
    store.add_job(conn, Job(employer="Old", title="Dev", start_date="2015", end_date="2017"))
    store.add_job(conn, Job(employer="Now", title="Dev", start_date="2022"))
    store.add_job(conn, Job(employer="Mid", title="Dev", start_date="2018", end_date="2021"))
    assert [j.employer for j in store.list_jobs(conn)] == ["Now", "Mid", "Old"]


def test_get_job_missing_raises(conn):
    with pytest.raises(store.NotFound):
        store.get_job(conn, 404)


# ── Experiences and facts ───────────────────────────────────────────────────


def test_add_experience_persists_facts(conn, experience):
    fetched = store.get_experience(conn, experience.id)
    assert fetched.summary.startswith("Migrated the billing service")
    assert fetched.facts_of(FactKind.TECHNOLOGY) == ["Kubernetes"]
    assert fetched.facts_of(FactKind.METRIC) == ["40% latency reduction"]
    assert fetched.display_id == f"EXP-{experience.id:03d}"


def test_duplicate_facts_are_ignored_not_fatal(conn, experience):
    store.add_fact(conn, experience.id, Fact(kind=FactKind.TECHNOLOGY, value="Kubernetes"))
    assert len(store.facts_for(conn, experience.id)) == 2


def test_list_experiences_filters_by_job(conn, job, experience):
    other = store.add_job(conn, Job(employer="Globex", title="Dev", start_date="2017"))
    store.add_experience(conn, Experience(job_id=other.id, summary="Something else."))

    assert len(store.list_experiences(conn)) == 2
    assert len(store.list_experiences(conn, job.id)) == 1
    assert len(store.list_experiences(conn, other.id)) == 1


def test_update_summary_changes_facts_not_identity(conn, experience):
    store.update_summary(conn, experience.id, "Corrected: cut p99 latency by 45%.")
    fetched = store.get_experience(conn, experience.id)
    assert "45%" in fetched.summary
    assert fetched.id == experience.id
    # Facts survive a summary correction.
    assert len(fetched.facts) == 2


def test_update_missing_experience_raises(conn):
    with pytest.raises(store.NotFound):
        store.update_summary(conn, 404, "nope")


def test_delete_experience(conn, experience):
    store.delete_experience(conn, experience.id)
    with pytest.raises(store.NotFound):
        store.get_experience(conn, experience.id)


# ── Tellings ────────────────────────────────────────────────────────────────


def test_many_tellings_per_experience(conn, experience):
    """The point of the model: one experience, many framings."""
    store.add_telling(
        conn,
        Telling(
            experience_id=experience.id,
            text="Led a migration that cut latency 40%.",
            angle="technical execution",
        ),
    )
    store.add_telling(
        conn,
        Telling(
            experience_id=experience.id,
            text="Coordinated five engineers across two orgs to land a migration.",
            angle="cross-functional leadership",
        ),
    )

    tellings = store.tellings_for(conn, experience.id)
    assert len(tellings) == 2
    assert {t.angle for t in tellings} == {"technical execution", "cross-functional leadership"}


def test_deleting_experience_removes_tellings(conn, experience):
    store.add_telling(
        conn, Telling(experience_id=experience.id, text="x", angle="y")
    )
    store.delete_experience(conn, experience.id)
    assert store.tellings_for(conn, experience.id) == []


def test_stats(conn, experience):
    counts = store.stats(conn)
    assert counts["jobs"] == 1
    assert counts["experiences"] == 1
    assert counts["facts"] == 2
    assert counts["tellings"] == 0
