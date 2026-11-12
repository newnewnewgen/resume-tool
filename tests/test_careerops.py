"""The career-ops bridge: parsing its documented artifact formats and the
qualification sweep. Fixtures are synthetic but follow the formats declared
in career-ops' DATA_CONTRACT.md / batch-prompt.md."""

from __future__ import annotations

import json

import pytest

from resume_tool import store
from resume_tool.careerops import (
    CareerOpsError,
    extract_jd,
    find_report,
    machine_summary,
    parse_pipeline,
    parse_tracker,
    qualify,
)
from resume_tool.models import Experience, Fact, FactKind, Job

PIPELINE = """\
# Pipeline

- [ ] https://boards.greenhouse.io/acme/jobs/123 | Acme | Product Manager | Remote | 120-140k | posted: 2026-10-01 | trust:high
- [x] #031 | https://jobs.lever.co/beta/456 | Beta | APM | Toronto | - | 4.2 | PDF
- [!] https://example.com/dead | Gone Inc | Ghost Role
not a pipeline line
"""

TRACKER = """\
| # | Date | Company | Role | Score | Status | PDF | Report | Notes | URL |
|---|------|---------|------|-------|--------|-----|--------|-------|-----|
| 31 | 2026-10-20 | [Beta](https://beta.co) | APM | 4.2/5 | Evaluated | - | [031](reports/031-beta-2026-10-20.md) | solid | [link](https://jobs.lever.co/beta/456) |
| 32 | 2026-10-21 | Acme | Product Manager | 4.7 | Evaluated | - | 032 | great fit | https://boards.greenhouse.io/acme/jobs/123 |
| 33 | 2026-10-22 | Gamma | PM | 3.1 | Evaluated | - | 033 | meh | - |
| 34 | 2026-10-23 | Delta | PM | 4.9 | Applied | ✓ | 034 | sent | - |
"""

REPORT = """\
# Evaluation: Acme — Product Manager

**Score: 4.7/5** | Decision: Apply

## Block B
...

## Job Description (archived verbatim)

We need someone with design system experience in Figma and customer
research skills. You will run discovery sessions.

## Machine Summary

```yaml
score: 4.7
final_decision: apply
archetype: product
```
"""


# ── parsers ─────────────────────────────────────────────────────────────────


def test_parse_pipeline_states_and_fields():
    items = parse_pipeline(PIPELINE)
    assert len(items) == 3
    assert items[0].state == "pending" and items[0].company == "Acme"
    assert items[1].state == "processed"
    assert items[1].url == "https://jobs.lever.co/beta/456"  # #NNN prefix skipped
    assert items[2].state == "inaccessible"


def test_parse_tracker_header_driven():
    rows = parse_tracker(TRACKER)
    assert [r.number for r in rows] == ["31", "32", "33", "34"]
    assert rows[0].company == "Beta"            # markdown link stripped
    assert rows[0].score == 4.2                 # "4.2/5" parsed
    assert rows[0].report_number == "031"
    assert rows[0].url == "https://jobs.lever.co/beta/456"
    assert rows[1].score == 4.7
    assert rows[3].status == "Applied"


def test_parse_tracker_tolerates_missing_optional_columns():
    no_url = "\n".join(
        "|".join(line.split("|")[:-2]) + "|"
        for line in TRACKER.splitlines()
    )
    rows = parse_tracker(no_url)
    assert rows and rows[0].company == "Beta"


def test_extract_jd_and_machine_summary():
    jd = extract_jd(REPORT)
    assert jd.startswith("We need someone")
    assert "Machine Summary" not in jd
    summary = machine_summary(REPORT)
    assert summary["score"] == 4.7
    assert summary["final_decision"] == "apply"


def test_report_without_jd_section():
    assert extract_jd("# Report\n\nNothing here") is None
    assert machine_summary("# Report\n") == {}


def test_find_report_matches_padded_numbers(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "031-beta-2026-10-20.md").write_text("x")
    assert find_report(tmp_path, "031").name.startswith("031-")
    assert find_report(tmp_path, "31").name.startswith("031-")
    assert find_report(tmp_path, "099") is None


# ── the qualification sweep ─────────────────────────────────────────────────


FAKE_PARSE = {
    "company": "Acme", "role_title": "Product Manager", "location": None,
    "knockouts": [{"id": "K1", "requirement": "US work authorization",
                   "evidence": "'authorized to work'"}],
    "requirements": [
        {"id": "R1", "tier": "critical", "kind": "skill",
         "requirement": "Design system experience in Figma",
         "evidence": "'design system experience in Figma'", "note": None},
        {"id": "R2", "tier": "critical", "kind": "skill",
         "requirement": "Customer research and discovery sessions",
         "evidence": "'customer research skills'", "note": None},
        {"id": "R3", "tier": "critical", "kind": "skill",
         "requirement": "Kernel driver development in Rust",
         "evidence": "'low-level systems'", "note": None},
    ],
    "signals": [],
}


@pytest.fixture
def career_ops_root(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "data" / "applications.md").write_text(TRACKER, encoding="utf-8")
    for num, slug in (("031", "beta"), ("032", "acme"), ("033", "gamma"), ("034", "delta")):
        (tmp_path / "reports" / f"{num}-{slug}-2026-10-20.md").write_text(
            REPORT, encoding="utf-8")
    return tmp_path


@pytest.fixture
def bank(conn):
    job = store.add_job(conn, Job(employer="Regulars", title="Growth PM", start_date="2026-01"))
    store.add_experience(conn, Experience(
        job_id=job.id,
        summary="Built the branded design system in Figma via the Figma MCP.",
        facts=[Fact(kind=FactKind.TECHNOLOGY, value="Figma")],
    ))
    store.add_experience(conn, Experience(
        job_id=job.id,
        summary="Led product discovery, running 15+ customer research sessions.",
    ))
    return conn


def test_qualify_scores_evaluated_rows_above_threshold(bank, career_ops_root):
    results = qualify(bank, career_ops_root, min_score=4.0, limit=5,
                      complete_fn=lambda s, p: json.dumps(FAKE_PARSE))
    # #34 is Applied (not Evaluated) and #33 is 3.1 — both excluded.
    assert [r.row.number for r in results] == ["32", "31"]  # sorted by their score
    fit = results[0].fit
    assert fit is not None
    covered = [f for f in fit.fits if f.covered]
    assert len(covered) == 2                 # Figma + discovery; Rust is a gap
    assert len(fit.gaps()) == 1


def test_qualify_limit(bank, career_ops_root):
    results = qualify(bank, career_ops_root, min_score=4.0, limit=1,
                      complete_fn=lambda s, p: json.dumps(FAKE_PARSE))
    assert len(results) == 1


def test_qualify_reports_missing_report_file(bank, career_ops_root):
    (career_ops_root / "reports" / "032-acme-2026-10-20.md").unlink()
    results = qualify(bank, career_ops_root, min_score=4.5, limit=5,
                      complete_fn=lambda s, p: json.dumps(FAKE_PARSE))
    assert results[0].error == "report file not found"


def test_qualify_requires_a_tracker(bank, tmp_path):
    with pytest.raises(CareerOpsError, match="applications.md"):
        qualify(bank, tmp_path)
