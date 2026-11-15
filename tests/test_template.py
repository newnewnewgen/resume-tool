"""Template tailoring: parse a Docs Markdown export, plan edits against it."""

from __future__ import annotations

import pytest

from resume_tool import store
from resume_tool.jd import ParsedJD, Requirement
from resume_tool.models import Experience, Job, RequirementKind, Tier
from resume_tool.scoring import score_fit
from resume_tool.template import headline_role, parse_template_markdown, plan_template

TEMPLATE = """\
# **Jane Doe \\| Associate Product Manager**

Springfield \\| 555-010-0100 \\| [jane@example.com](mailto:jane@example.com)

# **EXPERIENCE**

## **Growth PM** \t*Jan 2026 – Jul 2026*

## *Acme\tSpringfield*

* Built the branded design system in Figma, streamlining AI prototyping.
* Ran weekly A/B tests on ad creative, growing paid CTR by \\~45%.

# **PROJECTS**

## **Widget – Tool \\| [Website](https://example.com)** *Mar 2026*

* Shipped a widget tool to 50 users as sole builder.

# **SKILLS**

* Design: Figma
"""


def test_parse_export_structure():
    doc = parse_template_markdown(TEMPLATE)
    assert doc.title_line == "Jane Doe | Associate Product Manager"
    assert [e.section for e in doc.entries] == ["EXPERIENCE", "PROJECTS", "SKILLS"]
    acme = doc.entries[0]
    assert acme.heading.startswith("Growth PM") and acme.subheading.startswith("Acme")
    assert acme.bullets[1].endswith("CTR by ~45%.")      # escapes stripped
    assert doc.entries[1].heading.startswith("Widget – Tool | Website")  # link text kept


def test_parse_read_file_content_variant():
    md = "# **Jane \\| PM**\n# **EXPERIENCE**\n## **Role *2026***\n## ***Acme X***\n  - A bullet with \\$20,000.\n"
    doc = parse_template_markdown(md)
    assert doc.entries[0].bullets == ["A bullet with $20,000."]


def test_headline_role():
    assert headline_role("Apprentice Product Manager (APM) — 2027 cohort") == \
        "Apprentice Product Manager"
    assert headline_role("Senior PM") == "Senior PM"


@pytest.fixture
def bank(conn):
    job = store.add_job(conn, Job(employer="Acme", title="Growth PM", start_date="2026-01"))
    figma = store.add_experience(conn, Experience(
        job_id=job.id,
        summary="Built the branded design system in Figma, streamlining AI prototyping."))
    store.add_experience(conn, Experience(
        job_id=job.id, summary="Ran weekly A/B tests on ad creative, growing paid CTR by 45%."))
    discovery = store.add_experience(conn, Experience(
        job_id=job.id, summary="Led product discovery, running 15 customer research sessions."))
    return conn, figma, discovery


def test_plan_maps_bullets_and_finds_additions_and_gaps(bank):
    conn, figma, discovery = bank
    parsed = ParsedJD(company="Shop", role_title="Apprentice PM (APM)", location=None,
                      requirements=[
                          Requirement("R1", Tier.CRITICAL, RequirementKind.SKILL,
                                      "Design system experience in Figma", "e"),
                          Requirement("R2", Tier.CRITICAL, RequirementKind.SKILL,
                                      "Customer research and discovery sessions", "e"),
                          Requirement("R3", Tier.CRITICAL, RequirementKind.SKILL,
                                      "Kernel driver development in Rust", "e"),
                      ])
    plan = plan_template(conn, parse_template_markdown(TEMPLATE), parsed, score_fit(conn, parsed))

    assert plan.title_change == ("Jane Doe | Associate Product Manager",
                                 "Jane Doe | Apprentice PM")
    figma_bullet = next(b for b in plan.bullets if "design system" in b.text)
    assert figma_bullet.experience_id == figma.id and figma_bullet.covers == ["R1"]
    ab = next(b for b in plan.bullets if "A/B" in b.text)
    assert ab.verdict == "cut candidate"
    widget = next(b for b in plan.bullets if "widget" in b.text)
    assert widget.verdict == "not in bank"               # template story missing from the bank
    assert [a[0] for a in plan.additions] == ["R2"]       # bank covers it, template doesn't
    assert [g[0] for g in plan.gaps] == ["R3"]
    assert not any("Figma" == b.text for b in plan.bullets)  # skills section not planned


def test_docs_requests_only_automate_the_title(bank):
    conn, *_ = bank
    parsed = ParsedJD(company="Shop", role_title="Senior PM", location=None, requirements=[])
    plan = plan_template(conn, parse_template_markdown(TEMPLATE), parsed, score_fit(conn, parsed))
    requests = plan.docs_requests()
    assert len(requests) == 1
    assert requests[0]["replaceAllText"]["replaceText"] == "Jane Doe | Senior PM"
