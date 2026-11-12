"""The unified run: matching, truth-checked tellings, assembly, gates."""

from __future__ import annotations

import pytest

from resume_tool import store
from resume_tool.apply import format_result, run_apply
from resume_tool.jd import ParsedJD, Requirement
from resume_tool.models import (
    Experience, Fact, FactKind, Job, MatchState, RequirementKind, Telling, Tier,
)
from resume_tool.profile import Profile, load_profile, write_template
from resume_tool.render import Contact
from resume_tool.tellings import telling_for, truth_check


def req(rid, tier, text, evidence="evidence"):
    return Requirement(id=rid, tier=tier, kind=RequirementKind.SKILL,
                       requirement=text, evidence=evidence)


@pytest.fixture
def bank(conn):
    job = store.add_job(conn, Job(
        employer="Regulars", title="Growth PM", start_date="2026-01", end_date="2026-07"))
    figma = store.add_experience(conn, Experience(
        job_id=job.id,
        summary="Built the branded design system in Figma, accelerating AI "
                "prototyping 22x via the Figma MCP.",
        facts=[Fact(kind=FactKind.TECHNOLOGY, value="Figma"),
               Fact(kind=FactKind.METRIC, value="22x faster prototyping")],
    ))
    discovery = store.add_experience(conn, Experience(
        job_id=job.id,
        summary="Led product discovery, running 15 customer research sessions.",
        facts=[Fact(kind=FactKind.METRIC, value="15 research sessions")],
    ))
    return conn, figma, discovery


PARSED = ParsedJD(
    company="Acme", role_title="APM", location=None,
    requirements=[
        req("R1", Tier.CRITICAL, "Design system experience in Figma"),
        req("R2", Tier.CRITICAL, "Customer research and discovery sessions"),
        req("R3", Tier.CRITICAL, "Kernel driver development in Rust"),
    ],
)

PROFILE = Profile(contact=Contact(name="Jane Doe", email="jane@example.com",
                                  phone="555-010-0100", location="Springfield"),
                  skills=["Design: Figma"], education=[])


# ── truth check ─────────────────────────────────────────────────────────────


def test_truth_check_accepts_fact_numbers(bank):
    _, figma, _ = bank
    assert truth_check("Built a design system, 22x faster prototyping", figma) == []


def test_truth_check_catches_invented_numbers(bank):
    _, figma, _ = bank
    violations = truth_check("Drove $2.4M in revenue with 97% accuracy", figma)
    assert {v.value for v in violations} == {"2.4", "97"}


def test_telling_generation_rejects_fabrication_and_falls_back(bank):
    _, figma, _ = bank
    calls = []

    def liar(system, prompt):
        calls.append(prompt)
        return "Grew revenue 300% with the design system"  # fabricated twice

    text, source = telling_for(figma, "design systems", [], liar)
    assert source == "summary"              # refused to ship the fabrication
    assert text == figma.summary
    assert len(calls) == 2                  # one retry, with the violation named
    assert "300" in calls[1]


def test_telling_retry_can_recover(bank):
    _, figma, _ = bank
    answers = iter(["Shipped it 99x faster", "Built the Figma design system, 22x faster prototyping"])

    def flaky(system, prompt):
        return next(answers)

    text, source = telling_for(figma, "design systems", [], flaky)
    assert source == "generated"
    assert "22x" in text


def test_telling_reuses_matching_angle(bank):
    _, figma, _ = bank
    existing = [Telling(experience_id=figma.id, angle="design system work",
                        text="A stored telling.", id=1)]
    text, source = telling_for(figma, "design systems", existing, None)
    assert source == "reuse" and text == "A stored telling."


# ── the unified run ─────────────────────────────────────────────────────────


def test_run_apply_matches_persist_and_gaps_stay_gaps(bank, tmp_path):
    conn, figma, discovery = bank
    result = run_apply(conn, PARSED, "jd text", PROFILE, tmp_path, complete_fn=None)

    states = {d.requirement_label: d.state for d in result.decisions}
    assert states["R1"] == MatchState.PROPOSED
    assert states["R2"] == MatchState.PROPOSED
    assert states["R3"] == MatchState.GAP

    rows = conn.execute("SELECT state FROM requirement_match").fetchall()
    assert sorted(r["state"] for r in rows) == ["gap", "proposed", "proposed"]


def test_run_apply_assembles_a_passing_draft(bank, tmp_path):
    conn, *_ = bank
    result = run_apply(conn, PARSED, "jd", PROFILE, tmp_path, complete_fn=None)
    assert result.docx_path is not None and result.docx_path.exists()
    assert result.roundtrip_ok is True
    assert result.lint_clean is True
    assert all(source == "summary" for _, _, source in result.bullets)


def test_run_apply_without_profile_skips_assembly(bank, tmp_path):
    conn, *_ = bank
    result = run_apply(conn, PARSED, "jd", None, tmp_path, complete_fn=None)
    assert result.docx_path is None
    assert result.bullets                  # matching still ran


def test_format_result_prints_gaps_and_gates(bank, tmp_path):
    conn, *_ = bank
    parsed = ParsedJD(company="Acme", role_title="APM", location=None,
                      knockouts=[], requirements=PARSED.requirements)
    text = format_result(run_apply(conn, parsed, "jd", PROFILE, tmp_path))
    assert "GAP" in text and "EXP-" in text
    assert "round-trip PASS" in text


# ── profile ─────────────────────────────────────────────────────────────────


def test_profile_template_round_trips(tmp_path):
    path = write_template(tmp_path / "profile.yaml")
    content = path.read_text().replace('name: ""', 'name: "Jane Doe"') \
                              .replace('email: ""', 'email: "jane@example.com"')
    path.write_text(content)
    profile = load_profile(path)
    assert profile.contact.name == "Jane Doe"


def test_profile_requires_name_and_email(tmp_path):
    from resume_tool.profile import ProfileError
    path = write_template(tmp_path / "profile.yaml")
    with pytest.raises(ProfileError, match="contact.name"):
        load_profile(path)
