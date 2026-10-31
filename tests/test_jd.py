"""Step 4: JD parsing, worksheet rendering, storage, and the acceptance comparator.

No network and no API key: the LLM is a canned function. What the model
would return is simulated; everything after the model is tested for real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tool import store
from resume_tool.evals.jd import MATCH_THRESHOLD, compare
from resume_tool.jd import (
    JDParseError,
    load_worksheet_template,
    parse_jd,
    render_worksheet,
    store_application,
)
from resume_tool.models import RequirementKind, Tier

WORKSHEETS = Path(__file__).parent.parent / "worksheets"

GOOD_OUTPUT = {
    "company": "Acme",
    "role_title": "Associate PM",
    "location": "Springfield",
    "knockouts": [
        {"id": "K1", "requirement": "Authorized to work in the US",
         "evidence": "'Are you authorized to work...'"},
    ],
    "requirements": [
        {"id": "R1", "tier": "critical", "kind": "skill",
         "requirement": "Shipped a user-facing launch you can name",
         "evidence": "'experience with user-facing product launches'",
         "note": "named thing, real users, your role"},
        {"id": "R2", "tier": "critical", "kind": "skill",
         "requirement": "Complex SQL across multiple data sources",
         "evidence": "'comfortable building complex SQL queries'", "note": None},
        {"id": "R3", "tier": "important", "kind": "quality",
         "requirement": "Ramped on an unfamiliar domain fast, with a timeframe",
         "evidence": "'rapid pace across product areas'", "note": None},
        {"id": "R4", "tier": "nice_to_have", "kind": "domain",
         "requirement": "Grocery or convenience marketplaces",
         "evidence": "'100,000+ grocery stores'", "note": None},
    ],
    "signals": [
        {"id": "S1", "signal": "Why-us essay", "prep": "3-4 sentences, specific"},
    ],
}


def fake_llm(payload=GOOD_OUTPUT, wrap: str = ""):
    text = json.dumps(payload)
    if wrap == "fence":
        text = f"```json\n{text}\n```"
    return lambda system, prompt: text


# ── parse_jd ────────────────────────────────────────────────────────────────


def test_parse_jd_happy_path():
    parsed = parse_jd("a long JD", complete_fn=fake_llm())
    assert parsed.company == "Acme"
    assert len(parsed.knockouts) == 1
    assert len(parsed.requirements) == 4
    assert parsed.requirements[0].tier == Tier.CRITICAL
    assert parsed.requirements[3].kind == RequirementKind.DOMAIN
    assert parsed.signals[0].id == "S1"


def test_parse_jd_strips_code_fences():
    parsed = parse_jd("a JD", complete_fn=fake_llm(wrap="fence"))
    assert parsed.company == "Acme"


def test_parse_jd_passes_quality_bar_into_the_prompt():
    captured = {}

    def spy(system, prompt):
        captured["system"] = system
        captured["prompt"] = prompt
        return json.dumps(GOOD_OUTPUT)

    parse_jd("THE-JD-TEXT", complete_fn=spy)
    assert "verifiable from a resume bullet or a portfolio link" in captured["system"].lower() or \
           "verify it from a resume bullet" in captured["system"] or \
           "resume screener could verify" in captured["system"]
    assert "signals" in captured["system"]
    assert "THE-JD-TEXT" in captured["prompt"]


def test_parse_jd_rejects_empty_jd():
    with pytest.raises(JDParseError, match="empty"):
        parse_jd("   ", complete_fn=fake_llm())


def test_parse_jd_rejects_non_json():
    with pytest.raises(JDParseError, match="valid JSON"):
        parse_jd("a JD", complete_fn=lambda s, p: "Sure! Here are the requirements:")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(company=""), "company"),
        (lambda d: d["requirements"][0].update(tier="urgent"), "tier"),
        (lambda d: d["requirements"][0].update(kind="vibe"), "kind"),
        (lambda d: d["requirements"][0].update(kind="knockout"), "knockouts belong"),
        (lambda d: d["requirements"][1].update(id="R1"), "duplicate id"),
        (lambda d: d.update(knockouts=[]), "no knockouts"),
        (lambda d: d.update(requirements=d["requirements"][:2]
                            and [d["requirements"][3]] * 0 or []), "too few"),
    ],
)
def test_parse_jd_rejects_malformed_output(mutate, message):
    data = json.loads(json.dumps(GOOD_OUTPUT))
    mutate(data)
    with pytest.raises(JDParseError, match=message):
        parse_jd("a JD", complete_fn=fake_llm(data))


def test_parse_jd_requires_a_critical_tier():
    data = json.loads(json.dumps(GOOD_OUTPUT))
    for r in data["requirements"]:
        r["tier"] = "important"
    with pytest.raises(JDParseError, match="critical"):
        parse_jd("a JD", complete_fn=fake_llm(data))


# ── render ↔ load round trip ────────────────────────────────────────────────


def test_rendered_worksheet_is_valid_yaml_and_round_trips(tmp_path):
    parsed = parse_jd("a JD", complete_fn=fake_llm())
    path = tmp_path / "acme.yaml"
    path.write_text(render_worksheet(parsed, "acme.yaml"), encoding="utf-8")

    loaded = load_worksheet_template(path)
    assert loaded.company == parsed.company
    assert [r.id for r in loaded.requirements] == [r.id for r in parsed.requirements]
    assert [r.tier for r in loaded.requirements] == [r.tier for r in parsed.requirements]
    assert loaded.requirements[0].note == parsed.requirements[0].note
    assert [s.id for s in loaded.signals] == ["S1"]


def test_rendered_worksheet_has_fill_in_blanks():
    text = render_worksheet(parse_jd("a JD", complete_fn=fake_llm()))
    assert text.count('    your_experience: ""') == 4  # one per requirement
    assert "status:          # yes / no" in text
    assert "gitignored" in text  # the how-to-use header survived


def test_rendered_worksheet_escapes_hostile_strings(tmp_path):
    data = json.loads(json.dumps(GOOD_OUTPUT))
    data["requirements"][0]["requirement"] = 'Ship: "fast", #1 priority \\ always'
    parsed = parse_jd("a JD", complete_fn=fake_llm(data))
    path = tmp_path / "w.yaml"
    path.write_text(render_worksheet(parsed), encoding="utf-8")
    loaded = load_worksheet_template(path)
    assert loaded.requirements[0].requirement == 'Ship: "fast", #1 priority \\ always'


# ── the committed hand-built templates load as references ───────────────────


@pytest.mark.parametrize("name", ["figma-apm-2027.yaml", "doordash-new-verticals.yaml"])
def test_hand_built_templates_load_as_references(name):
    parsed = load_worksheet_template(WORKSHEETS / name)
    assert parsed.knockouts, name
    assert any(r.tier == Tier.CRITICAL for r in parsed.requirements), name


# ── storage ─────────────────────────────────────────────────────────────────


def test_store_application_writes_requirements(conn):
    parsed = parse_jd("the jd text", complete_fn=fake_llm())
    application_id = store_application(conn, parsed, "the jd text")

    rows = store.requirements_for(conn, application_id)
    assert len(rows) == 5  # 1 knockout + 4 requirements
    assert rows[0]["kind"] == "knockout"
    assert rows[1]["kind"] == "skill"
    assert rows[1]["evidence"].startswith("'experience")
    assert rows[1]["note"] == "named thing, real users, your role"
    assert rows[4]["kind"] == "domain"  # schema v2 accepts it


def test_schema_v1_database_migrates_to_v2(tmp_path):
    import sqlite3

    from resume_tool.db import SCHEMA_VERSION, open_db, schema_version
    from resume_tool.db.connection import connect

    # Build a v1 database by hand: v1 schema had no 'domain' kind and no
    # evidence/note columns.
    path = tmp_path / "old.db"
    conn = connect(path)
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE application (id INTEGER PRIMARY KEY, company TEXT NOT NULL,
            role_title TEXT NOT NULL, jd_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE requirement (id INTEGER PRIMARY KEY,
            application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            tier TEXT NOT NULL CHECK (tier IN ('critical','important','nice_to_have')),
            kind TEXT NOT NULL CHECK (kind IN ('knockout','skill','quality')),
            position INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE requirement_match (id INTEGER PRIMARY KEY,
            requirement_id INTEGER NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
            state TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    conn.execute("INSERT INTO application (company, role_title, jd_text) VALUES ('A','B','C')")
    conn.execute(
        "INSERT INTO requirement (application_id, text, tier, kind) "
        "VALUES (1, 'old row', 'critical', 'skill')"
    )
    conn.commit()
    conn.close()

    conn = open_db(path)
    assert schema_version(conn) == SCHEMA_VERSION
    # Old data survived, new kind and columns work, FKs still cascade.
    row = conn.execute("SELECT * FROM requirement").fetchone()
    assert row["text"] == "old row" and row["evidence"] is None
    conn.execute(
        "INSERT INTO requirement (application_id, text, tier, kind, evidence) "
        "VALUES (1, 'new row', 'nice_to_have', 'domain', 'quoted')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO requirement (application_id, text, tier, kind) "
            "VALUES (1, 'bad', 'critical', 'vibes')"
        )
    conn.execute("DELETE FROM application WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) AS n FROM requirement").fetchone()["n"] == 0
    conn.close()


# ── the acceptance comparator ───────────────────────────────────────────────


def _mini(requirements):
    data = json.loads(json.dumps(GOOD_OUTPUT))
    data["requirements"] = requirements
    return parse_jd("a JD", complete_fn=fake_llm(data))


def test_compare_scores_full_coverage():
    ref = parse_jd("a JD", complete_fn=fake_llm())
    report = compare(generated=ref, reference=ref)
    assert report.coverage == 1.0
    assert report.tier_agreement == 1.0
    assert report.extra_generated == 0


def test_compare_detects_a_miss_and_an_extra():
    ref = parse_jd("a JD", complete_fn=fake_llm())
    gen = _mini([
        {"id": "G1", "tier": "critical", "kind": "skill",
         "requirement": "Complex SQL queries across multiple data sources",
         "evidence": "e", "note": None},
        {"id": "G2", "tier": "critical", "kind": "skill",
         "requirement": "Underwater basket weaving at production scale",
         "evidence": "e", "note": None},
        {"id": "G3", "tier": "important", "kind": "skill",
         "requirement": "Shipped a user-facing launch you can name",
         "evidence": "e", "note": None},
    ])
    report = compare(generated=gen, reference=ref)
    assert report.covered == 2  # SQL + launch matched; ramp + grocery missed
    assert report.extra_generated == 1  # basket weaving
    launch = next(m for m in report.matches if m.reference.id == "R1")
    assert launch.matched and not launch.tier_agrees  # critical vs important
    assert any(not m.matched for m in report.matches)
    assert "missed reference requirements" in str(report)


def test_compare_threshold_blocks_weak_matches():
    from resume_tool.jd import ParsedJD, Requirement

    def one(req_id, text):
        return ParsedJD(
            company="A", role_title="B", location=None,
            requirements=[Requirement(
                id=req_id, tier=Tier.CRITICAL, kind=RequirementKind.SKILL,
                requirement=text, evidence="e")],
        )

    ref = one("R1", "Designing, launching and reading out experiments")
    gen = one("G1", "Managing vendor procurement contracts")
    report = compare(generated=gen, reference=ref)
    assert report.coverage == 0.0
    assert report.matches[0].score < MATCH_THRESHOLD
