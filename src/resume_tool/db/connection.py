"""SQLite connection handling and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """requirement gains the 'domain' kind plus evidence/note columns.

    SQLite cannot alter a CHECK, so the table is rebuilt. Renaming the old
    table away would rewrite child FK clauses to point at the new name, so
    instead: build requirement_new, drop requirement, rename new into place —
    with FK enforcement off for the duration.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("""
        CREATE TABLE requirement_new (
            id             INTEGER PRIMARY KEY,
            application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
            text           TEXT NOT NULL,
            tier           TEXT NOT NULL CHECK (tier IN ('critical','important','nice_to_have')),
            kind           TEXT NOT NULL CHECK (kind IN ('knockout','skill','quality','domain')),
            evidence       TEXT,
            note           TEXT,
            position       INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO requirement_new (id, application_id, text, tier, kind, position)
            SELECT id, application_id, text, tier, kind, position FROM requirement;
        DROP TABLE requirement;
        ALTER TABLE requirement_new RENAME TO requirement;
        CREATE INDEX idx_requirement_app ON requirement(application_id);
    """)
    conn.execute("PRAGMA foreign_keys = ON")


_MIGRATIONS = {2: _migrate_v2}


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced and rows accessible by name.

    SQLite disables foreign key enforcement by default and it is per-connection, so it
    must be switched on every time — a silent source of orphaned rows otherwise.
    """
    path = Path(db_path)
    if path.parent != Path("") and str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    """Create the schema, or migrate an older one forward."""
    if not _schema_present(conn):
        conn.executescript(_SCHEMA_FILE.read_text())
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
        return

    version = schema_version(conn) or 0
    while version < SCHEMA_VERSION:
        version += 1
        _MIGRATIONS[version](conn)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.commit()


def schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the installed schema version, or None if the schema is absent."""
    if not _schema_present(conn):
        return None
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] if row else None


def _schema_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    return row is not None


def open_db(db_path: Path | str) -> sqlite3.Connection:
    """Connect and ensure the schema exists."""
    conn = connect(db_path)
    initialize(conn)
    return conn
