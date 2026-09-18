"""Schema integrity: constraints must be enforced at the database level."""

from __future__ import annotations

import sqlite3

import pytest

from resume_tool.db import SCHEMA_VERSION, open_db, schema_version


def test_initialize_is_idempotent(tmp_path):
    path = tmp_path / "bank.db"
    open_db(path).close()
    conn = open_db(path)
    assert schema_version(conn) == SCHEMA_VERSION
    conn.close()


def test_expected_tables_exist(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {
        "job", "experience", "experience_fact", "experience_embedding",
        "telling", "application", "requirement", "requirement_match",
    } <= names


def test_foreign_keys_are_enforced(conn):
    # Easy to get wrong: SQLite disables FK enforcement by default, per connection.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO experience (job_id, summary) VALUES (?, ?)", (999, "orphan")
        )


def test_deleting_a_job_cascades(conn, experience, job):
    conn.execute("DELETE FROM job WHERE id = ?", (job.id,))
    conn.commit()
    remaining = conn.execute("SELECT COUNT(*) AS n FROM experience").fetchone()["n"]
    facts = conn.execute("SELECT COUNT(*) AS n FROM experience_fact").fetchone()["n"]
    assert remaining == 0
    assert facts == 0


@pytest.mark.parametrize(
    "table,columns,values",
    [
        ("experience_fact", "(experience_id, kind, value)", (1, "bogus", "x")),
        ("requirement", "(application_id, text, tier, kind)", (1, "t", "urgent", "skill")),
        ("requirement_match", "(requirement_id, state)", (1, "maybe")),
    ],
)
def test_check_constraints_reject_bad_enums(conn, experience, table, columns, values):
    placeholders = ", ".join("?" for _ in values)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO {table} {columns} VALUES ({placeholders})", values)


def test_duplicate_facts_are_rejected(conn, experience):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO experience_fact (experience_id, kind, value) VALUES (?, ?, ?)",
            (experience.id, "technology", "Kubernetes"),
        )
