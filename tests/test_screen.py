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
