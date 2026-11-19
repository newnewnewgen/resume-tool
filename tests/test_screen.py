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


def test_workday_board_and_age():
    from resume_tool.screen import posted_days_ago, workday_board
    assert workday_board("https://visa.wd5.myworkdayjobs.com/Visa") == (
        "https://visa.wd5.myworkdayjobs.com/wday/cxs/visa/Visa/jobs", "https://visa.wd5.myworkdayjobs.com/Visa")
    assert workday_board("https://wd5.myworkdaysite.com/recruiting/guidewire/external")[1] == \
        "https://wd5.myworkdaysite.com/recruiting/guidewire/external"
    assert workday_board("https://jobs.lever.co/x") is None
    assert posted_days_ago("Posted Today") == 0
    assert posted_days_ago("Posted Yesterday") == 1
    assert posted_days_ago("Posted 5 Days Ago") == 5
    assert posted_days_ago("Posted 30+ Days Ago") is None


def test_scan_workday_appends_early_product_roles(tmp_path, monkeypatch):
    from resume_tool.screen import parse_pipeline, scan_workday, workday_search
    page = {"total": 4, "jobPostings": [
        {"title": "Associate Product Manager", "externalPath": "/job/Toronto/APM_R1",
         "locationsText": "Toronto", "postedOn": "Posted 2 Days Ago"},
        {"title": "Senior Product Manager", "externalPath": "/job/X/SPM_R2", "postedOn": "Posted Today"},
        {"title": "Product Designer", "externalPath": "/job/X/PD_R3", "postedOn": "Posted Today"},
        {"title": "Product Manager", "externalPath": "/job/X/PM_R4", "postedOn": "Posted 30+ Days Ago"},
    ]}
    portals = tmp_path / "portals.yml"
    portals.write_text("tracked_companies:\n"
                       "  - {name: Visa, careers_url: 'https://visa.wd5.myworkdayjobs.com/Visa', enabled: false}\n"
                       "  - {name: Stripe, careers_url: 'https://job-boards.greenhouse.io/stripe'}\n")
    pipeline = tmp_path / "pipeline.md"
    pipeline.write_text("## Pending\n\n- [ ] https://job-boards.greenhouse.io/stripe/jobs/1 | stripe | PM\n")

    def search(url, since_days):
        return workday_search(url, since_days=since_days, post=lambda api, body: page)

    monkeypatch.setattr("resume_tool.screen.time.sleep", lambda s: None)

    added, errors = scan_workday(portals, pipeline, since_days=7, pause=0, search=search)
    assert (added, errors) == (1, [])
    items = parse_pipeline(pipeline.read_text())
    assert [i.title for i in items] == ["PM", "Associate Product Manager"]
    assert items[1].url == "https://visa.wd5.myworkdayjobs.com/Visa/job/Toronto/APM_R1"
    assert scan_workday(portals, pipeline, since_days=7, pause=0, search=search)[0] == 0  # dedup


def test_product_facets_picks_product_families_only():
    from resume_tool.screen import product_facets
    facets = [
        {"facetParameter": "jobFamilyGroup", "values": [
            {"descriptor": "Engineering", "id": "e1"},
            {"descriptor": "Product Management", "id": "p1"},
            {"descriptor": "Product Marketing", "id": "pm1"}]},
        {"facetParameter": "locations", "values": [{"descriptor": "Product City", "id": "x"}]},
        {"facetParameter": "jobFamilyGroup_nested", "values": [
            {"facetParameter": "jobFamily", "values": [{"descriptor": "Product", "id": "p2"}]}]},
    ]
    assert product_facets(facets) == {"jobFamilyGroup": ["p1"], "jobFamily": ["p2"]}


def test_years_in_words_and_mid_titles():
    from resume_tool.screen import early_product_title
    assert years_required("- Three or more years of advanced client support experience.") == 3
    assert years_required("Five (5) years of product experience") == 5
    assert not early_product_title("Manager, Product Management")
    assert not early_product_title("Regional Product Manager, APAC")
    assert not early_product_title("Networking MBA Product Manager Graduate")
    assert early_product_title("Associate Product Manager")
    assert early_product_title("Product Analyst I")
