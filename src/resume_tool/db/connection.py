"""SQLite connection handling and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1
_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


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
    """Create the schema. No-op if it already exists."""
    if _schema_present(conn):
        return
    conn.executescript(_SCHEMA_FILE.read_text())
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
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
