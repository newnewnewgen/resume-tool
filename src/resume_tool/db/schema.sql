-- Resume tool schema.
--
-- Core principle: facts are durable, narrative is disposable.
--   experience  = what actually happened. Canonical. Never rewritten per application.
--   telling     = one framing of an experience. Regenerable. Many per experience.
--
-- Note: the spec calls the match table `match`; MATCH is a SQLite keyword, so it is
-- named `requirement_match` here to avoid permanent quoting.

CREATE TABLE schema_version (
    version    INTEGER NOT NULL,
    applied_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Durable layer: jobs, experiences, facts ─────────────────────────────────

CREATE TABLE job (
    id         INTEGER PRIMARY KEY,
    employer   TEXT NOT NULL,
    title      TEXT NOT NULL,
    start_date TEXT NOT NULL,            -- ISO-ish: 'YYYY' or 'YYYY-MM'
    end_date   TEXT,                     -- NULL = current role
    location   TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (employer, title, start_date)
);

-- The canonical record of something that happened. Facts only — no framing.
CREATE TABLE experience (
    id         INTEGER PRIMARY KEY,
    job_id     INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    summary    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Structured facts, separately queryable. Powers the truth check: every number and
-- technology in a generated telling must trace back to a row here.
CREATE TABLE experience_fact (
    id            INTEGER PRIMARY KEY,
    experience_id INTEGER NOT NULL REFERENCES experience(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL CHECK (
                      kind IN ('metric','technology','scope','collaborator','outcome')),
    value         TEXT NOT NULL,
    UNIQUE (experience_id, kind, value)
);

-- Tracks which model produced the vector, so a model change can invalidate stale rows.
CREATE TABLE experience_embedding (
    experience_id INTEGER PRIMARY KEY REFERENCES experience(id) ON DELETE CASCADE,
    vector        BLOB    NOT NULL,
    dim           INTEGER NOT NULL,
    model         TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Disposable layer: tellings ──────────────────────────────────────────────

CREATE TABLE telling (
    id            INTEGER PRIMARY KEY,
    experience_id INTEGER NOT NULL REFERENCES experience(id) ON DELETE CASCADE,
    text          TEXT NOT NULL,
    angle         TEXT NOT NULL,         -- what this framing emphasizes
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Application layer ───────────────────────────────────────────────────────

CREATE TABLE application (
    id         INTEGER PRIMARY KEY,
    company    TEXT NOT NULL,
    role_title TEXT NOT NULL,
    jd_text    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'draft' CHECK (
                   status IN ('draft','in_review','complete','abandoned')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE requirement (
    id             INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    text           TEXT NOT NULL,
    tier           TEXT NOT NULL CHECK (tier IN ('critical','important','nice_to_have')),
    kind           TEXT NOT NULL CHECK (kind IN ('knockout','skill','quality')),
    position       INTEGER NOT NULL DEFAULT 0
);

-- User decisions. Persistent, so re-running against an edited JD re-validates choices
-- instead of discarding them. state='gap' means no experience covers this requirement.
CREATE TABLE requirement_match (
    id             INTEGER PRIMARY KEY,
    requirement_id INTEGER NOT NULL REFERENCES requirement(id) ON DELETE CASCADE,
    experience_id  INTEGER REFERENCES experience(id) ON DELETE SET NULL,
    telling_id     INTEGER REFERENCES telling(id)    ON DELETE SET NULL,
    state          TEXT NOT NULL CHECK (
                       state IN ('proposed','approved','rejected','gap')),
    score          REAL,
    decided_at     TEXT,
    UNIQUE (requirement_id, experience_id)
);

-- ── Indexes ─────────────────────────────────────────────────────────────────

CREATE INDEX idx_experience_job        ON experience(job_id);
CREATE INDEX idx_fact_experience       ON experience_fact(experience_id);
CREATE INDEX idx_telling_experience    ON telling(experience_id);
CREATE INDEX idx_requirement_app       ON requirement(application_id);
CREATE INDEX idx_match_requirement     ON requirement_match(requirement_id);
CREATE INDEX idx_match_experience      ON requirement_match(experience_id);
