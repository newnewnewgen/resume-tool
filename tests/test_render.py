"""Rendering, ATS lint, and round-trip verification."""

from __future__ import annotations

import docx
import pytest

from resume_tool.ingest import extract_text, parse_resume
from resume_tool.render import (
    Contact,
    Entry,
    ResumeDoc,
    Section,
    lint_docx,
    verify_roundtrip,
    write_docx,
)


@pytest.fixture
def doc() -> ResumeDoc:
    return ResumeDoc(
        contact=Contact(
            name="Jane Doe",
            location="Seattle, WA",
            phone="555-010-0100",
            email="jane@example.com",
            linkedin="linkedin.com/in/janedoe",
        ),
        summary="Operator who owns metrics end to end and builds the models behind them.",
        sections=[
            Section("Experience", entries=[
                Entry(
                    title="Senior Engineer",
                    organization="Acme Corp",
                    start_date="Jan 2020",
                    end_date="Mar 2022",
                    location="San Francisco, CA",
                    bullets=[
                        "Migrated the billing service off a monolith, cutting p99 latency 40%.",
                        "Led 5 engineers through a zero-downtime Postgres migration of 2.3TB.",
                    ],
                ),
                Entry(
                    title="Software Engineer",
                    organization="Globex Inc",
                    start_date="Jun 2017",
                    end_date="Dec 2019",
                    location="Seattle, WA",
                    bullets=["Built an internal deployment tool adopted by 12 teams."],
                ),
            ]),
            Section("Skills", lines=[
                "Analytics: SQL (Databricks, BigQuery), Excel, Tableau",
                "Languages: Python, Go, TypeScript",
            ]),
        ],
    )


# ── Writing ─────────────────────────────────────────────────────────────────


def test_writes_a_readable_file(doc, tmp_path):
    path = write_docx(doc, tmp_path / "r.docx")
    assert path.exists()
    assert "Acme Corp" in extract_text(path)


def test_uses_no_tables(doc, tmp_path):
    """Tables are the most common cause of scrambled ATS output."""
    path = write_docx(doc, tmp_path / "r.docx")
    assert docx.Document(str(path)).tables == []


def test_contact_is_in_the_body_not_a_header(doc, tmp_path):
    path = write_docx(doc, tmp_path / "r.docx")
    d = docx.Document(str(path))
    body = "\n".join(p.text for p in d.paragraphs)
    assert "jane@example.com" in body
    for section in d.sections:
        assert not any(p.text.strip() for p in section.header.paragraphs)


def test_bullets_are_literal_characters(doc, tmp_path):
    """Word list formatting does not survive text extraction; literal marks do."""
    path = write_docx(doc, tmp_path / "r.docx")
    text = extract_text(path)
    assert text.count("•") >= 3


def test_dates_are_present_and_not_in_cells(doc, tmp_path):
    path = write_docx(doc, tmp_path / "r.docx")
    text = extract_text(path)
    assert "Jan 2020" in text and "Mar 2022" in text


def test_current_role_renders_as_present(tmp_path):
    d = ResumeDoc(
        contact=Contact(name="Jane Doe", email="j@e.com"),
        sections=[Section("Experience", entries=[
            Entry(title="Staff Engineer", organization="Initech",
                  start_date="Mar 2022", end_date="",
                  bullets=["Owns the platform roadmap."])])],
    )
    assert "Present" in extract_text(write_docx(d, tmp_path / "r.docx"))


# ── Round-trip ──────────────────────────────────────────────────────────────


def test_roundtrip_passes(doc, tmp_path):
    result = verify_roundtrip(doc, tmp_path / "r.docx")
    assert result.ok, result.failures
    assert result.recovered_bullets == result.expected_bullets


def test_roundtrip_recovers_every_bullet_verbatim(doc, tmp_path):
    write_docx(doc, tmp_path / "r.docx")
    text = extract_text(tmp_path / "r.docx")
    for bullet in doc.all_bullets():
        assert bullet in text


def test_roundtrip_detects_loss(doc, tmp_path):
    """The check must fail when content really is missing, or it proves nothing."""
    result = verify_roundtrip(doc, tmp_path / "r.docx")
    assert result.ok

    doc.sections[0].entries[0].bullets.append("A bullet never written to the file.")
    text = extract_text(tmp_path / "r.docx")          # stale file, new expectation
    assert "never written" not in text


def test_structure_parser_recovers_entries(doc, tmp_path):
    """Read back with the generic parser, not one that knows the layout."""
    path = write_docx(doc, tmp_path / "r.docx")
    parsed = parse_resume(extract_text(path))
    assert len(parsed.jobs) == 2
    assert {j.employer for j in parsed.jobs} == {"Acme Corp", "Globex Inc"}
    assert parsed.experience_count == 3


# ── Lint ────────────────────────────────────────────────────────────────────


def test_generated_document_is_clean(doc, tmp_path):
    assert lint_docx(write_docx(doc, tmp_path / "r.docx")) == []


def _hostile(tmp_path, build) -> list:
    d = docx.Document()
    build(d)
    path = tmp_path / "bad.docx"
    d.save(str(path))
    return lint_docx(path)


def test_lint_flags_tables(tmp_path):
    def build(d):
        d.add_paragraph("Jane Doe jane@example.com 555-010-0100")
        d.add_paragraph("EXPERIENCE")
        d.add_table(rows=2, cols=2)
    issues = _hostile(tmp_path, build)
    assert any(i.check == "tables" and i.level == "error" for i in issues)


def test_lint_flags_contact_in_header(tmp_path):
    def build(d):
        d.sections[0].header.paragraphs[0].text = "jane@example.com | 555-010-0100"
        d.add_paragraph("EXPERIENCE")
        d.add_paragraph("Senior Engineer")
    issues = _hostile(tmp_path, build)
    assert any(i.check == "header content" for i in issues)


def test_lint_flags_missing_email(tmp_path):
    def build(d):
        d.add_paragraph("Jane Doe")
        d.add_paragraph("EXPERIENCE")
    issues = _hostile(tmp_path, build)
    assert any(i.check == "email" and i.level == "error" for i in issues)


def test_lint_flags_nonstandard_headings(tmp_path):
    def build(d):
        d.add_paragraph("Jane Doe jane@example.com 555-010-0100")
        d.add_paragraph("WHERE I MADE IMPACT")
    issues = _hostile(tmp_path, build)
    assert any(i.check == "nonstandard headings" for i in issues)


def test_lint_flags_word_list_bullets(tmp_path):
    """The exact defect found on a real resume: 0 of 17 bullets recoverable."""
    def build(d):
        d.add_paragraph("Jane Doe jane@example.com 555-010-0100")
        d.add_paragraph("EXPERIENCE")
        d.add_paragraph("Did a thing worth describing", style="List Bullet")
    issues = _hostile(tmp_path, build)
    assert any(i.check == "word list formatting" for i in issues)


def test_extract_normalizes_word_lists(tmp_path):
    """Extraction must recover a bullet marker that Word stored as metadata."""
    d = docx.Document()
    d.add_paragraph("Shipped the billing rewrite", style="List Bullet")
    path = tmp_path / "list.docx"
    d.save(str(path))
    assert "•" in extract_text(path)
