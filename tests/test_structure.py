"""Deterministic resume structure detection."""

from __future__ import annotations

import pytest

from resume_tool.ingest.structure import find_date_range, normalize_date, parse_resume

from conftest import SAMPLE_RESUME


# ── Date normalization ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Jan 2020", "2020-01"),
        ("January 2020", "2020-01"),
        ("Sept 2019", "2019-09"),
        ("Dec. 2021", "2021-12"),
        ("June 2017", "2017-06"),
        ("01/2020", "2020-01"),
        ("12-2021", "2021-12"),
        ("2020", "2020"),
        ("Present", None),
        ("current", None),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


@pytest.mark.parametrize(
    "line,start,end",
    [
        ("Jan 2020 - Mar 2022", "2020-01", "2022-03"),
        ("June 2017 – December 2019", "2017-06", "2019-12"),
        ("2018 to 2021", "2018", "2021"),
        ("Mar 2021 — Present", "2021-03", None),
        ("Engineer | Acme | 01/2020 - 03/2022", "2020-01", "2022-03"),
    ],
)
def test_find_date_range(line, start, end):
    found = find_date_range(line)
    assert found is not None
    assert (found[0], found[1]) == (start, end)


def test_no_date_range_returns_none():
    assert find_date_range("Built an internal deployment tool") is None


# ── Full parse ──────────────────────────────────────────────────────────────


def test_parses_jobs_from_sample():
    result = parse_resume(SAMPLE_RESUME)
    assert len(result.jobs) == 2

    first, second = result.jobs
    assert first.employer == "Acme Corp"
    assert first.title == "Senior Engineer"
    assert first.start_date == "2020-01"
    assert first.end_date == "2022-03"

    assert second.employer == "Globex Inc"
    assert second.title == "Software Engineer"
    assert second.end_date == "2019-12"


def test_education_is_not_parsed_as_a_job():
    """The education line has a year; section detection must exclude it."""
    result = parse_resume(SAMPLE_RESUME)
    employers = {j.employer for j in result.jobs}
    assert not any("University" in e for e in employers)


def test_extracts_experiences_per_job():
    result = parse_resume(SAMPLE_RESUME)
    assert [len(j.experiences) for j in result.jobs] == [2, 2]
    assert result.experience_count == 4


def test_wrapped_bullet_lines_are_joined():
    result = parse_resume(SAMPLE_RESUME)
    ci_bullet = result.jobs[1].experiences[1].summary
    assert "parallelizing the test suite across runners" in ci_bullet
    assert "\n" not in ci_bullet


def test_current_role_has_no_end_date():
    text = """\
EXPERIENCE

Staff Engineer | Initech | Mar 2022 - Present
• Owns the platform roadmap.
"""
    result = parse_resume(text)
    assert result.jobs[0].end_date is None
    assert result.jobs[0].start_date == "2022-03"


def test_stacked_layout_flags_low_confidence():
    """Dates on their own line: parseable, but the tool must say it guessed."""
    text = """\
EXPERIENCE

Acme Corp — Senior Engineer
Jan 2020 - Mar 2022
• Did a thing that mattered a great deal.
"""
    result = parse_resume(text)
    assert len(result.jobs) == 1
    assert result.jobs[0].notes, "an adjacent-line guess must be flagged for review"


def test_empty_input_is_handled():
    result = parse_resume("")
    assert result.jobs == []
    assert result.notes


def test_no_dates_reports_rather_than_crashes():
    result = parse_resume("Jane Doe\nI have done many things.\n")
    assert result.jobs == []
    assert any("date" in n.lower() for n in result.notes)


def test_numbered_bullets_are_recognized():
    text = """\
EXPERIENCE

Engineer | Acme | 2020 - 2022
1. Shipped the first version of the billing service.
2. Cut deployment time from an hour to ten minutes.
"""
    result = parse_resume(text)
    assert len(result.jobs[0].experiences) == 2
