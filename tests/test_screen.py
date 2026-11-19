"""Deterministic posting screen: years, degree gate, graduation lines."""

from __future__ import annotations

from resume_tool.screen import (
    EARLY_TITLE, PRODUCT_TITLE, Screened, cs_degree_required, graduation_lines,
    years_required,
)


def test_years_required_takes_the_bar_not_noise():
    assert years_required("- 4+ years of experience in product management") == 4
    assert years_required("6+ years experience in the software industry\nPaid month off after 4 years") == 6
    assert years_required("New grad or 0-2 years of professional experience") == 0  # range: the entry bar
    assert years_required("We were founded 10 years ago.") is None
    assert years_required("No requirement stated.") is None


def test_cs_degree_gate():
    assert cs_degree_required("New grad, with a CS or engineering degree.")
    assert cs_degree_required("Bachelor's degree in computer science or related field")
    assert not cs_degree_required("Bachelor's degree in any field, or equivalent experience")


def test_graduation_lines():
    text = "About us\nYou will graduate in Fall 2026 or Spring 2027\nPerks"
    assert graduation_lines(text) == ["You will graduate in Fall 2026 or Spring 2027"]


def test_title_classifiers():
    assert PRODUCT_TITLE.search("Associate Product Manager, New Grad")
    assert PRODUCT_TITLE.search("APX (New Grad 2027)")
    assert EARLY_TITLE.search("Product Manager: New Grad Accelerator")
    assert not EARLY_TITLE.search("Product Manager, Radar")


def test_within_rule():
    def s(**kw):
        return Screened(company="c", title="t", url="u", years_required=kw.get("y"),
                        cs_degree_required=False, early_title=kw.get("early", False))
    assert s(y=None).within and s(y=2).within
    assert not s(y=4).within
    assert s(y=4, early=True).within          # early-career title wins; knockouts decide


def test_workday_detail_url_both_shapes():
    from resume_tool.screen import workday_detail_url
    assert workday_detail_url(
        "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/Toronto/Associate-Product-Manager_JR1"
    ) == ("https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site"
          "/job/Toronto/Associate-Product-Manager_JR1")
    assert workday_detail_url(
        "https://visa.wd5.myworkdayjobs.com/en-US/Visa/job/Foster-City/APM_REF1"
    ) == "https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/Visa/job/Foster-City/APM_REF1"
    assert workday_detail_url(
        "https://wd5.myworkdaysite.com/recruiting/guidewire/external/job/Toronto/APM_JR2"
    ) == "https://wd5.myworkdaysite.com/wday/cxs/guidewire/external/job/Toronto/APM_JR2"
    assert workday_detail_url("https://job-boards.greenhouse.io/stripe/jobs/1") is None


def test_fetch_jd_routes_by_posting_url(monkeypatch):
    from resume_tool import screen
    calls = []

    def fake_get(url):
        calls.append(url)
        if "/wday/cxs/" in url:
            return {"jobPostingInfo": {"title": "Associate Product Manager",
                                       "jobDescription": "<p>0-2 years of experience</p>"}}
        if "smartrecruiters" in url:
            return {"name": "APM", "jobAd": {"sections": {"jobDescription": {"text": "<p>Own a roadmap</p>"}}}}
        return {"title": "APM", "description": "<p>Ship</p>", "requirements": None}

    monkeypatch.setattr(screen, "_get", fake_get)
    text = screen.fetch_jd("", "https://redhat.wd5.myworkdayjobs.com/jobs/job/Raleigh/APM_R1")
    assert text.startswith("Associate Product Manager") and "0-2 years" in text
    assert "Own a roadmap" in screen.fetch_jd("", "https://jobs.smartrecruiters.com/LinkedIn3/7440-apm")
    assert calls[-1] == "https://api.smartrecruiters.com/v1/companies/LinkedIn3/postings/7440"
    assert "Ship" in screen.fetch_jd("", "https://apply.workable.com/raydar/j/ABC123/")
    assert calls[-1] == "https://apply.workable.com/api/v2/accounts/raydar/jobs/ABC123"
