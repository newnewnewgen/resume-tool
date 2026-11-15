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


# ── coverage is a floor, not a filter ───────────────────────────────────────


def test_jobs_without_matches_still_appear(bank, tmp_path):
    conn, *_ = bank
    other = store.add_job(conn, Job(employer="Achievers", title="Co-op",
                                    start_date="2025-05", end_date="2025-12"))
    for summary in ("Owned the GTM launch of a Microsoft integration.",
                    "Ran surveys and market sizing for a product expansion.",
                    "Designed enablement content for three personas."):
        store.add_experience(conn, Experience(job_id=other.id, summary=summary))

    result = run_apply(conn, PARSED, "jd", PROFILE, tmp_path, complete_fn=None)
    planned = {store.get_experience(conn, e).job_id for e, _, _ in result.bullets}
    assert other.id in planned                       # the unmatched job survived
    from_other = [e for e, _, _ in result.bullets
                  if store.get_experience(conn, e).job_id == other.id]
    assert len(from_other) == 2                      # capped for unmatched jobs


def test_matched_job_keeps_more_bullets(bank, tmp_path):
    conn, figma, discovery = bank
    regulars = figma.job_id
    for summary in ("Built AI agents for GTM qualification.",
                    "Closed the product's first two clients.",
                    "Scoped features with engineering."):
        store.add_experience(conn, Experience(job_id=regulars, summary=summary))
    result = run_apply(conn, PARSED, "jd", PROFILE, tmp_path, complete_fn=None)
    from_regulars = [e for e, _, _ in result.bullets
                     if store.get_experience(conn, e).job_id == regulars]
    assert len(from_regulars) == 4                   # matched first, then filler, capped
    assert from_regulars[:2] == [figma.id, discovery.id] or \
           set(from_regulars[:2]) == {figma.id, discovery.id}


def test_project_employers_render_under_projects(bank, tmp_path):
    from resume_tool.ingest import extract_text
    conn, *_ = bank
    pj = store.add_job(conn, Job(employer="Independent Projects", title="Builder",
                                 start_date="2024-01"))
    store.add_experience(conn, Experience(
        job_id=pj.id, summary="Shipped a Figma design system plugin to 50 users."))
    profile = Profile(contact=PROFILE.contact, project_employers=["Independent Projects"])
    result = run_apply(conn, PARSED, "jd", profile, tmp_path, complete_fn=None)
    text = extract_text(result.docx_path)
    assert "PROJECTS" in text.upper()
    assert "Builder" not in text                     # not rendered as a job
    assert "Shipped a Figma design system plugin" in text


# ── assembly: dates, section order, fitting one page ────────────────────────


def test_human_dates():
    from resume_tool.apply import _human_date
    assert _human_date("2026-07") == "Jul 2026"
    assert _human_date("2026") == "2026"
    assert _human_date("Sep 2021") == "Sep 2021"
    assert _human_date(None) == ""


def test_section_order_follows_profile(bank, tmp_path):
    from resume_tool.ingest import extract_text
    from resume_tool.render import Entry
    conn, *_ = bank
    profile = Profile(contact=PROFILE.contact, skills=["Design: Figma"],
                      education=[Entry(title="State U", organization="B.Com",
                                       start_date="Sep 2021", end_date="May 2026")],
                      section_order=["Education", "Experience", "Skills"])
    result = run_apply(conn, PARSED, "jd", profile, tmp_path, complete_fn=None)
    text = extract_text(result.docx_path).upper()
    assert text.index("EDUCATION") < text.index("EXPERIENCE") < text.index("SKILLS")


def test_page_fit_cuts_filler_never_matches_or_whole_jobs(bank, tmp_path, monkeypatch):
    import resume_tool.apply as apply_mod
    conn, figma, discovery = bank
    other = store.add_job(conn, Job(employer="Achievers", title="Co-op",
                                    start_date="2025-05", end_date="2025-12"))
    for summary in ("Owned a GTM launch.", "Ran market sizing."):
        store.add_experience(conn, Experience(job_id=other.id, summary=summary))

    # Fake renderer: over one page until at most 3 bullets remain.
    def fake_pages(path):
        from resume_tool.ingest import extract_text
        return 1 if extract_text(path).count("•") <= 3 else 2
    monkeypatch.setattr(apply_mod, "_page_count", fake_pages)

    result = run_apply(conn, PARSED, "jd", PROFILE, tmp_path, complete_fn=None)
    assert result.pages == 1
    assert result.cut_to_fit                         # something was cut
    kept = [e for e, _, _ in result.bullets]
    from resume_tool.ingest import extract_text
    text = extract_text(result.docx_path)
    assert figma.summary.split(",")[0] in text       # matched bullets survive
    assert "Achievers" in text                       # the job survives with 1 bullet


def test_page_fit_unchecked_without_renderer(bank, tmp_path, monkeypatch):
    import resume_tool.apply as apply_mod
    monkeypatch.setattr(apply_mod, "_page_count", lambda path: None)
    conn, *_ = bank
    result = run_apply(conn, PARSED, "jd", PROFILE, tmp_path, complete_fn=None)
    assert result.pages is None and not result.cut_to_fit
    assert "unchecked" in format_result(result)
