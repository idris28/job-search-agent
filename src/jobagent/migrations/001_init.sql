-- Job Search Agent: initial schema (PostgreSQL 14+)

-- The candidate profile the agent matches against (parsed from a resume).
CREATE TABLE profiles (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    resume_text     TEXT NOT NULL,
    profile         JSONB NOT NULL,           -- structured: skills, years, titles, locations, preferences
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Where jobs come from: one row per configured board/search (e.g. a Greenhouse company board).
CREATE TABLE sources (
    id              BIGSERIAL PRIMARY KEY,
    kind            TEXT NOT NULL,            -- greenhouse | lever | generic
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kind, url)
);

-- One agent execution (scrape + match).
CREATE TABLE runs (
    id              BIGSERIAL PRIMARY KEY,
    profile_id      BIGINT REFERENCES profiles(id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'succeeded', 'failed', 'partial')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    jobs_found      INT NOT NULL DEFAULT 0,
    jobs_new        INT NOT NULL DEFAULT 0,
    jobs_scored     INT NOT NULL DEFAULT 0,
    tokens_used     INT NOT NULL DEFAULT 0,
    error           TEXT,
    config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Per-source / per-step log lines for a run (debugging and history).
CREATE TABLE run_events (
    id              BIGSERIAL PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source_id       BIGINT REFERENCES sources(id) ON DELETE SET NULL,
    level           TEXT NOT NULL DEFAULT 'info' CHECK (level IN ('debug', 'info', 'warning', 'error')),
    message         TEXT NOT NULL,
    data            JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX run_events_run_idx ON run_events (run_id, created_at);

-- Every distinct posting seen. Deduped by fingerprint (normalized company + title + location).
CREATE TABLE jobs (
    id              BIGSERIAL PRIMARY KEY,
    source_id       BIGINT REFERENCES sources(id) ON DELETE SET NULL,
    external_id     TEXT,
    fingerprint     TEXT NOT NULL UNIQUE,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,
    remote_type     TEXT CHECK (remote_type IN ('remote', 'hybrid', 'onsite', 'unknown')),
    employment_type TEXT,
    salary_text     TEXT,
    description     TEXT,
    posted_at       TIMESTAMPTZ,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_run_id    BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    raw             JSONB
);
CREATE INDEX jobs_last_seen_idx ON jobs (last_seen_at DESC);
CREATE INDEX jobs_company_idx ON jobs (lower(company));

-- LLM match result for a (profile, job) pair. Re-scored only when the job text changes.
CREATE TABLE job_matches (
    id              BIGSERIAL PRIMARY KEY,
    profile_id      BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    job_id          BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    run_id          BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    score           SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 100),
    verdict         TEXT NOT NULL CHECK (verdict IN ('strong', 'good', 'stretch', 'poor')),
    summary         TEXT NOT NULL,
    matched_skills  TEXT[] NOT NULL DEFAULT '{}',
    missing_skills  TEXT[] NOT NULL DEFAULT '{}',
    red_flags       TEXT[] NOT NULL DEFAULT '{}',
    model           TEXT NOT NULL,
    content_hash    TEXT NOT NULL,            -- hash of job text scored; changes trigger re-score
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (profile_id, job_id)
);
CREATE INDEX job_matches_score_idx ON job_matches (profile_id, score DESC);

-- What the person did about a job. The agent never submits applications itself.
CREATE TABLE applications (
    id              BIGSERIAL PRIMARY KEY,
    profile_id      BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    job_id          BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'shortlisted'
                    CHECK (status IN ('shortlisted', 'applied', 'interviewing', 'offer',
                                      'rejected', 'withdrawn', 'skipped')),
    cover_letter    TEXT,                      -- optional AI draft, for the person to edit
    notes           TEXT,
    applied_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (profile_id, job_id)
);

-- Status history so the pipeline is auditable.
CREATE TABLE application_events (
    id              BIGSERIAL PRIMARY KEY,
    application_id  BIGINT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
