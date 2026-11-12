"""Fit scoring: the intake qualifier (bank coverage of a parsed JD)."""

from __future__ import annotations

import pytest

from resume_tool import store
from resume_tool.jd import ParsedJD, Requirement
from resume_tool.models import Experience, Fact, FactKind, Job, RequirementKind, Tier
from resume_tool.scoring import APPLY_AT, STRETCH_AT, FitReport, score_fit


def req(rid, tier, text, evidence="evidence"):
    return Requirement(id=rid, tier=tier, kind=RequirementKind.SKILL,
                       requirement=text, evidence=evidence)


def jd(*requirements):
    return ParsedJD(company="Acme", role_title="APM", location=None,
                    requirements=list(requirements))


@pytest.fixture
def bank(conn):
    job = store.add_job(conn, Job(employer="Regulars", title="Growth PM", start_date="2026-01"))
    store.add_experience(conn, Experience(
        job_id=job.id,
        summary="Built the branded design system in Figma, streamlining AI "
                "prototyping and GTM asset generation via the Figma MCP.",
        facts=[Fact(kind=FactKind.TECHNOLOGY, value="Figma")],
    ))
    store.add_experience(conn, Experience(
        job_id=job.id,
        summary="Led product discovery, running 15+ customer research sessions "
                "to identify user stories and pain points.",
    ))
    return conn


def test_full_coverage_is_apply(bank):
    report = score_fit(bank, jd(
        req("R1", Tier.CRITICAL, "Design system experience in Figma"),
        req("R2", Tier.CRITICAL, "Customer research and discovery sessions"),
    ))
    assert report.verdict == "APPLY"
    assert report.weighted_score == 1.0
    assert not report.gaps()


def test_zero_coverage_is_skip(bank):
    report = score_fit(bank, jd(
        req("R1", Tier.CRITICAL, "Kernel driver development in Rust"),
        req("R2", Tier.CRITICAL, "FedRAMP compliance certification audits"),
    ))
    assert report.verdict == "SKIP"
    assert len(report.gaps(Tier.CRITICAL)) == 2


def test_critical_gaps_outweigh_nice_to_haves(bank):
    # One critical gap + covered nice-to-haves should hurt much more than
    # the reverse: tier weighting is the point of the qualifier.
    critical_gap = score_fit(bank, jd(
        req("R1", Tier.CRITICAL, "Kernel driver development in Rust"),
        req("R2", Tier.NICE_TO_HAVE, "Figma design system familiarity"),
    ))
    nice_gap = score_fit(bank, jd(
        req("R1", Tier.CRITICAL, "Figma design system experience"),
        req("R2", Tier.NICE_TO_HAVE, "Kernel driver development in Rust"),
    ))
    assert nice_gap.weighted_score > critical_gap.weighted_score
    assert nice_gap.verdict == "APPLY"
    assert critical_gap.verdict == "SKIP"


def test_empty_bank_says_so(conn):
    report = score_fit(conn, jd(req("R1", Tier.CRITICAL, "Anything at all")))
    assert report.verdict == "NO BANK"
    assert report.bank_experiences == 0


def test_evidence_contributes_to_retrieval(bank):
    # Requirement text is abstract; the JD evidence carries the concrete noun.
    report = score_fit(bank, jd(
        req("R1", Tier.CRITICAL, "Hands-on with modern design tooling",
            evidence="'experience with Figma design systems'"),
    ))
    assert report.fits[0].covered


def test_report_renders_with_gaps(bank):
    report = score_fit(bank, jd(
        req("R1", Tier.CRITICAL, "Kernel driver development in Rust"),
        req("R2", Tier.IMPORTANT, "Figma design systems"),
    ))
    text = str(report)
    assert "critical gaps" in text
    assert "R1" in text
    assert "verdict" in text


def test_thresholds_are_ordered():
    assert 0 < STRETCH_AT < APPLY_AT < 1
    assert FitReport(parsed=jd(), bank_experiences=1).weighted_score == 0.0
