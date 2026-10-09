"""Eval harness: golden set loading, scoring, and the baseline retriever."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tool import retrieval, store
from resume_tool.evals import GoldenError, evaluate, load_golden
from resume_tool.evals.golden import build_bank
from resume_tool.models import Experience, Fact, FactKind, Job
from resume_tool.retrieval import Candidate, tokenize

GOLDEN = Path(__file__).parent.parent / "evals" / "golden.yaml"


# ── Tokenizer ────────────────────────────────────────────────────────────────


def test_tokenize_stems_inflections():
    assert tokenize("owning owned owns") == {"own"}
    assert tokenize("dashboards metrics") == {"dashboard", "metric"}
    assert tokenize("designing launched experiments") == {"design", "launch", "experiment"}


def test_tokenize_drops_stopwords_and_keeps_compounds():
    tokens = tokenize("the cross-functional team with A/B tests")
    assert "the" not in tokens and "with" not in tokens
    assert "cross-functional" in tokens
    assert "a/b" in tokens


def test_tokenize_keeps_numbers():
    assert "61" in tokenize("baseline 61% acceptance")


# ── Baseline retriever ───────────────────────────────────────────────────────


@pytest.fixture
def bank(conn):
    job = store.add_job(conn, Job(employer="Acme", title="Analyst", start_date="2020"))
    sql = store.add_experience(
        conn,
        Experience(
            job_id=job.id,
            summary="Built complex SQL reports across multiple data sources.",
            facts=[Fact(kind=FactKind.TECHNOLOGY, value="SQL")],
        ),
    )
    dash = store.add_experience(
        conn,
        Experience(job_id=job.id, summary="Maintained the metrics dashboard in Looker."),
    )
    return {"sql": sql, "dash": dash}


def test_retrieve_ranks_the_obvious_match_first(conn, bank):
    candidates = retrieval.retrieve(conn, "complex SQL across multiple data sources")
    assert candidates
    assert candidates[0].experience_id == bank["sql"].id


def test_retrieve_drops_zero_scores(conn, bank):
    assert retrieval.retrieve(conn, "FedRAMP compliance certification") == []


def test_retrieve_respects_k(conn, bank):
    candidates = retrieval.retrieve(conn, "SQL dashboard metrics data", k=1)
    assert len(candidates) == 1


def test_facts_count_toward_the_score(conn):
    job = store.add_job(conn, Job(employer="Acme", title="Analyst", start_date="2020"))
    experience = store.add_experience(
        conn,
        Experience(
            job_id=job.id,
            summary="Automated the quarterly review deck.",
            facts=[Fact(kind=FactKind.TECHNOLOGY, value="Claude API")],
        ),
    )
    candidates = retrieval.retrieve(conn, "Claude API automation")
    assert candidates and candidates[0].experience_id == experience.id


# ── Golden set loading ───────────────────────────────────────────────────────


def test_committed_golden_set_loads():
    golden = load_golden(GOLDEN)
    assert len(golden.cases) >= 10
    assert any(c.expects_gap for c in golden.cases)
    assert any(not c.expects_gap for c in golden.cases)


def test_committed_golden_bank_builds(conn):
    golden = load_golden(GOLDEN)
    ids_by_ref = build_bank(conn, golden)
    assert len(ids_by_ref) == len(golden.experiences)


def _golden_file(tmp_path, body: str) -> Path:
    path = tmp_path / "golden.yaml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = """
jobs:
  - ref: j1
    employer: Acme
    title: Analyst
    start_date: 2020
experiences:
  - ref: e1
    job: j1
    summary: Built SQL reports.
cases:
  - id: C1
    tier: critical
    requirement: SQL reporting
    expect: e1
"""


def test_minimal_golden_set_parses(tmp_path):
    golden = load_golden(_golden_file(tmp_path, MINIMAL))
    assert golden.cases[0].expect == ["e1"]


@pytest.mark.parametrize(
    ("mangle", "message"),
    [
        (lambda s: s.replace("expect: e1", "expect: nope"), "unknown experience ref"),
        (lambda s: s.replace("tier: critical", "tier: mild"), "tier"),
        (lambda s: s.replace("job: j1", "job: j9"), "does not match a job ref"),
        (lambda s: s.replace("requirement: SQL reporting", "requirement: ''"), "requirement"),
    ],
)
def test_malformed_golden_sets_are_rejected(tmp_path, mangle, message):
    with pytest.raises(GoldenError, match=message):
        load_golden(_golden_file(tmp_path, mangle(MINIMAL)))


def test_duplicate_case_ids_are_rejected(tmp_path):
    body = MINIMAL + """
  - id: C1
    tier: critical
    requirement: Something else
    expect: gap
"""
    with pytest.raises(GoldenError, match="duplicate case id"):
        load_golden(_golden_file(tmp_path, body))


def test_missing_golden_file():
    with pytest.raises(GoldenError, match="not found"):
        load_golden("does-not-exist.yaml")


# ── Runner scoring ───────────────────────────────────────────────────────────


GAP_AND_MATCH = """
jobs:
  - ref: j1
    employer: Acme
    title: Analyst
    start_date: 2020
experiences:
  - ref: e1
    job: j1
    summary: Built SQL reports.
  - ref: e2
    job: j1
    summary: Ran the weekly metrics review.
cases:
  - id: C1
    tier: critical
    requirement: SQL reporting
    expect: e1
  - id: C2
    tier: critical
    requirement: FedRAMP compliance
    expect: gap
"""


def test_perfect_retriever_scores_100(tmp_path):
    golden = load_golden(_golden_file(tmp_path, GAP_AND_MATCH))

    def perfect(conn, requirement, k):
        if "SQL" in requirement:
            return [Candidate(experience_id=1, score=0.9)]
        return []

    report = evaluate(golden, retrieve_fn=perfect)
    assert report.accuracy == 1.0
    assert not report.forced_matches
    assert not report.false_gaps


def test_forced_match_is_detected(tmp_path):
    golden = load_golden(_golden_file(tmp_path, GAP_AND_MATCH))

    def overconfident(conn, requirement, k):
        return [Candidate(experience_id=1, score=0.9)]

    report = evaluate(golden, retrieve_fn=overconfident)
    assert len(report.forced_matches) == 1
    assert report.forced_matches[0].case.id == "C2"


def test_false_gap_is_detected(tmp_path):
    golden = load_golden(_golden_file(tmp_path, GAP_AND_MATCH))

    def timid(conn, requirement, k):
        return []

    report = evaluate(golden, retrieve_fn=timid)
    assert len(report.false_gaps) == 1
    assert report.false_gaps[0].case.id == "C1"
    # The gap case is still correct — only the real match was missed.
    assert report.correct == 1


def test_low_scores_below_threshold_become_gaps(tmp_path):
    golden = load_golden(_golden_file(tmp_path, GAP_AND_MATCH))

    def weak(conn, requirement, k):
        return [Candidate(experience_id=1, score=0.05)]

    report = evaluate(golden, retrieve_fn=weak, gap_threshold=0.2)
    assert all(r.predicted_gap for r in report.results)


def test_rank_is_recorded_for_top_k_hits(tmp_path):
    golden = load_golden(_golden_file(tmp_path, GAP_AND_MATCH))

    def second_place(conn, requirement, k):
        if "SQL" in requirement:
            return [
                Candidate(experience_id=2, score=0.8),
                Candidate(experience_id=1, score=0.7),
            ]
        return []

    report = evaluate(golden, retrieve_fn=second_place)
    sql_case = next(r for r in report.results if r.case.id == "C1")
    assert sql_case.correct and sql_case.rank == 2


# ── The committed golden set under the committed baseline ───────────────────
#
# Deterministic end to end, so these are stable. The floor is set below the
# current score (13/14) to leave room for editing the set without churn; the
# gap guarantees are exact because forcing a match is never acceptable.


def test_baseline_on_committed_golden_set():
    report = evaluate(load_golden(GOLDEN))
    assert report.accuracy >= 0.75
    assert not report.forced_matches

    gap_cases = [r for r in report.results if r.case.expects_gap]
    assert gap_cases and all(r.predicted_gap for r in gap_cases)


def test_report_renders():
    report = evaluate(load_golden(GOLDEN))
    text = str(report)
    assert "overall" in text
    assert "forced match(es)" in text
