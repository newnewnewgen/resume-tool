"""Loading a filled requirements worksheet into the bank."""

from __future__ import annotations

import pytest
import yaml

from resume_tool import store
from resume_tool.models import FactKind
from resume_tool.worksheet import WorksheetError, load_worksheet


def write(tmp_path, payload) -> str:
    p = tmp_path / "w.yaml"
    p.write_text(yaml.safe_dump(payload, sort_keys=False))
    return str(p)


@pytest.fixture
def worksheet(tmp_path):
    return write(tmp_path, {
        "jobs": [
            {"ref": "LA", "employer": "Level Access", "title": "Product Marketing Specialist",
             "start_date": "2026-07", "end_date": "", "location": "Vancouver, BC"},
            {"ref": "REG", "employer": "Regulars", "title": "Growth Product Manager",
             "start_date": "2026-01", "end_date": "2026-06", "location": "Vancouver, BC"},
        ],
        "experiences": [
            {"ref": "EXP-A", "job": "LA", "covers": ["R1"],
             "summary": "Built rolling Power BI dashboards on SQL over Databricks lakehouses.",
             "facts": [
                 {"kind": "technology", "value": "Power BI"},
                 {"kind": "technology", "value": "Databricks lakehouses"},
             ]},
            {"ref": "EXP-I", "job": "REG", "covers": ["R10"],
             "summary": "Set pricing across subscription, transaction and pay-per-use revenue.",
             "facts": [{"kind": "outcome", "value": "pricing adopted by 3 early clients"}]},
        ],
    })


def test_loads_jobs_experiences_and_facts(conn, worksheet):
    result = load_worksheet(conn, worksheet)
    assert result.jobs_created == 2
    assert result.experiences_created == 2
    assert result.facts_created == 3

    assert len(store.list_jobs(conn)) == 2
    experiences = store.list_experiences(conn)
    assert len(experiences) == 2
    tech = [f.value for e in experiences for f in e.facts if f.kind == FactKind.TECHNOLOGY]
    assert "Power BI" in tech and "Databricks lakehouses" in tech


def test_experiences_land_under_the_right_job(conn, worksheet):
    load_worksheet(conn, worksheet)
    by_employer = {j.employer: j for j in store.list_jobs(conn)}
    la = store.list_experiences(conn, by_employer["Level Access"].id)
    reg = store.list_experiences(conn, by_employer["Regulars"].id)
    assert len(la) == 1 and "Power BI" in la[0].summary
    assert len(reg) == 1 and "pricing" in reg[0].summary


def test_reloading_is_idempotent(conn, worksheet):
    load_worksheet(conn, worksheet)
    second = load_worksheet(conn, worksheet)
    assert second.jobs_created == 0
    assert second.experiences_created == 0
    assert second.experiences_skipped == 2
    assert len(store.list_experiences(conn)) == 2


def test_multiline_summaries_are_normalized(conn, tmp_path):
    """YAML block scalars carry newlines; the bank should hold one clean line."""
    path = tmp_path / "w.yaml"
    path.write_text(
        "jobs:\n"
        "- ref: A\n  employer: Acme\n  title: Engineer\n  start_date: '2020-01'\n"
        "experiences:\n"
        "- job: A\n"
        "  summary: |\n"
        "    Migrated the billing service\n"
        "    off the monolith.\n"
    )
    load_worksheet(conn, path)
    assert store.list_experiences(conn)[0].summary == \
        "Migrated the billing service off the monolith."


def test_unknown_job_ref_names_the_valid_refs(conn, tmp_path):
    path = write(tmp_path, {
        "jobs": [{"ref": "LA", "employer": "Acme", "title": "Eng", "start_date": "2020"}],
        "experiences": [{"job": "NOPE", "summary": "Something happened."}],
    })
    with pytest.raises(WorksheetError) as exc:
        load_worksheet(conn, path)
    assert "NOPE" in str(exc.value) and "LA" in str(exc.value)


@pytest.mark.parametrize("payload,fragment", [
    ({"jobs": [{"employer": "A", "title": "T", "start_date": "2020"}]}, "ref"),
    ({"jobs": [{"ref": "A", "title": "T", "start_date": "2020"}]}, "employer"),
    ({"jobs": [{"ref": "A", "employer": "A", "title": "T", "start_date": "nope"}]}, "YYYY"),
])
def test_invalid_jobs_are_rejected(conn, tmp_path, payload, fragment):
    with pytest.raises(WorksheetError) as exc:
        load_worksheet(conn, write(tmp_path, payload))
    assert fragment in str(exc.value)


def test_invalid_fact_kind_lists_valid_options(conn, tmp_path):
    path = write(tmp_path, {
        "jobs": [{"ref": "A", "employer": "Acme", "title": "Eng", "start_date": "2020"}],
        "experiences": [{"job": "A", "summary": "Did a thing.",
                         "facts": [{"kind": "vibe", "value": "good"}]}],
    })
    with pytest.raises(WorksheetError) as exc:
        load_worksheet(conn, path)
    assert "technology" in str(exc.value)


def test_missing_file(conn, tmp_path):
    with pytest.raises(WorksheetError):
        load_worksheet(conn, tmp_path / "nope.yaml")
