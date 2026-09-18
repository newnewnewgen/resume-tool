"""Text extraction and the draft round-trip."""

from __future__ import annotations

import pytest
import yaml

from resume_tool import store
from resume_tool.ingest import (
    DraftError,
    UnsupportedFormat,
    commit_draft,
    extract_text,
    load_draft,
    parse_resume,
    write_draft,
)

from conftest import SAMPLE_RESUME


# ── Extraction ──────────────────────────────────────────────────────────────


def test_extract_txt(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text(SAMPLE_RESUME, encoding="utf-8")
    assert "Acme Corp" in extract_text(path)


def test_extract_docx(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "resume.docx"
    document = docx.Document()
    for line in SAMPLE_RESUME.split("\n"):
        document.add_paragraph(line)
    document.save(str(path))

    text = extract_text(path)
    assert "Acme Corp" in text
    assert "Globex Inc" in text


def test_extract_unsupported_format(tmp_path):
    path = tmp_path / "resume.pages"
    path.write_text("x")
    with pytest.raises(UnsupportedFormat):
        extract_text(path)


def test_extract_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_text(tmp_path / "nope.txt")


# ── Draft round-trip ────────────────────────────────────────────────────────


def test_draft_is_valid_yaml_and_reloads(tmp_path):
    result = parse_resume(SAMPLE_RESUME)
    path = write_draft(result, tmp_path / "draft.yaml")

    data = yaml.safe_load(path.read_text())
    assert len(data["jobs"]) == 2

    jobs = load_draft(path)
    assert jobs[0]["employer"] == "Acme Corp"


def test_draft_carries_parser_notes(tmp_path):
    text = """\
EXPERIENCE

Acme Corp — Senior Engineer
Jan 2020 - Mar 2022
• Did a thing worth describing here.
"""
    path = write_draft(parse_resume(text), tmp_path / "draft.yaml")
    assert "notes" in path.read_text()


def test_commit_writes_to_database(conn, tmp_path):
    path = write_draft(parse_resume(SAMPLE_RESUME), tmp_path / "draft.yaml")
    result = commit_draft(conn, path)

    assert result.jobs_created == 2
    assert result.experiences_created == 4
    assert len(store.list_jobs(conn)) == 2
    assert len(store.list_experiences(conn)) == 4


def test_commit_twice_is_idempotent(conn, tmp_path):
    """Re-importing an edited draft must not double the bank."""
    path = write_draft(parse_resume(SAMPLE_RESUME), tmp_path / "draft.yaml")
    commit_draft(conn, path)
    second = commit_draft(conn, path)

    assert second.jobs_created == 0
    assert second.jobs_existing == 2
    assert second.experiences_created == 0
    assert second.experiences_skipped == 4
    assert len(store.list_jobs(conn)) == 2
    assert len(store.list_experiences(conn)) == 4


def test_recommit_after_editing_adds_only_the_new(conn, tmp_path):
    """The real workflow: commit, notice something missing, add it, re-commit."""
    path = write_draft(parse_resume(SAMPLE_RESUME), tmp_path / "draft.yaml")
    commit_draft(conn, path)

    data = yaml.safe_load(path.read_text())
    data["jobs"][0]["experiences"].append(
        {"summary": "Wrote the on-call runbook the team still uses.", "facts": []}
    )
    path.write_text(yaml.safe_dump(data))

    result = commit_draft(conn, path)
    assert result.experiences_created == 1
    assert result.experiences_skipped == 4
    assert len(store.list_experiences(conn)) == 5


def test_same_summary_under_different_jobs_is_kept(conn, tmp_path):
    """Dedup is scoped to a job — the same work at two employers is two experiences."""
    path = tmp_path / "draft.yaml"
    shared = "Ran the migration."
    path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "employer": "Acme",
                        "title": "Engineer",
                        "start_date": "2020-01",
                        "experiences": [{"summary": shared, "facts": []}],
                    },
                    {
                        "employer": "Globex",
                        "title": "Engineer",
                        "start_date": "2017-01",
                        "experiences": [{"summary": shared, "facts": []}],
                    },
                ]
            }
        )
    )
    result = commit_draft(conn, path)
    assert result.experiences_created == 2
    assert result.experiences_skipped == 0


def test_full_date_in_draft_is_accepted_and_truncated(conn, tmp_path):
    """Hand-writing 'YYYY-MM-DD' in a draft is natural; accept and truncate it."""
    path = tmp_path / "draft.yaml"
    path.write_text(
        "jobs:\n"
        "- employer: Acme\n"
        "  title: Engineer\n"
        "  start_date: '2020-01-15'\n"
        "  experiences:\n"
        "  - summary: Shipped the billing rewrite.\n"
    )
    commit_draft(conn, path)
    assert store.list_jobs(conn)[0].start_date == "2020-01"


def test_notes_are_not_imported(conn, tmp_path):
    path = tmp_path / "draft.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "employer": "Acme",
                        "title": "Engineer",
                        "start_date": "2020-01",
                        "end_date": "",
                        "notes": ["verify this"],
                        "experiences": [{"summary": "Shipped the thing.", "facts": []}],
                    }
                ]
            }
        )
    )
    commit_draft(conn, path)
    assert len(store.list_experiences(conn)) == 1


def test_commit_imports_facts(conn, tmp_path):
    path = tmp_path / "draft.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "employer": "Acme",
                        "title": "Engineer",
                        "start_date": "2020-01",
                        "experiences": [
                            {
                                "summary": "Cut latency.",
                                "facts": [
                                    {"kind": "metric", "value": "40%"},
                                    {"kind": "technology", "value": "Go"},
                                ],
                            }
                        ],
                    }
                ]
            }
        )
    )
    commit_draft(conn, path)
    experience = store.list_experiences(conn)[0]
    assert len(experience.facts) == 2


# ── Validation ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({"nope": []}, "jobs"),
        ({"jobs": "not a list"}, "must be a list"),
        ({"jobs": [{"title": "T", "start_date": "2020"}]}, "employer"),
        ({"jobs": [{"employer": "A", "start_date": "2020"}]}, "title"),
        ({"jobs": [{"employer": "A", "title": "T"}]}, "start_date"),
        ({"jobs": [{"employer": "A", "title": "T", "start_date": "nope"}]}, "YYYY"),
    ],
)
def test_invalid_drafts_are_rejected(tmp_path, payload, fragment):
    path = tmp_path / "draft.yaml"
    path.write_text(yaml.safe_dump(payload))
    with pytest.raises(DraftError) as exc:
        load_draft(path)
    assert fragment in str(exc.value)


def test_bad_fact_kind_is_rejected_with_valid_options(tmp_path):
    path = tmp_path / "draft.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "employer": "A",
                        "title": "T",
                        "start_date": "2020",
                        "experiences": [
                            {"summary": "x", "facts": [{"kind": "vibe", "value": "y"}]}
                        ],
                    }
                ]
            }
        )
    )
    with pytest.raises(DraftError) as exc:
        load_draft(path)
    assert "technology" in str(exc.value)


def test_malformed_yaml_is_reported(tmp_path):
    path = tmp_path / "draft.yaml"
    path.write_text("jobs: [unclosed")
    with pytest.raises(DraftError):
        load_draft(path)


def test_missing_draft_file(tmp_path):
    with pytest.raises(DraftError):
        load_draft(tmp_path / "nope.yaml")
