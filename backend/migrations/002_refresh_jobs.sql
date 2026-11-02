-- Extend the phase-1 placeholder into a durable, fenced queue.
ALTER TABLE jobs ADD COLUMN scope_key TEXT;
ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'history';
ALTER TABLE jobs ADD COLUMN league_id TEXT REFERENCES leagues(id);
ALTER TABLE jobs ADD COLUMN available_at REAL NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN finished_at TEXT;
ALTER TABLE jobs ADD COLUMN worker_id TEXT;
ALTER TABLE jobs ADD COLUMN result_json TEXT;
-- Placeholder jobs from before the worker existed cannot be executed safely.
UPDATE jobs SET state='failed', error_code='legacy_job' WHERE state IN ('queued','running');
CREATE UNIQUE INDEX jobs_active_scope ON jobs(scope_key) WHERE state IN ('queued','running');
CREATE INDEX jobs_ready ON jobs(state,available_at);
CREATE TABLE refresh_scopes (
    scope_key TEXT PRIMARY KEY,
    not_before REAL NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_result_json TEXT
);
CREATE TABLE automatic_attempts (
    id INTEGER PRIMARY KEY,
    scope_key TEXT NOT NULL,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    attempted_at REAL NOT NULL
);
CREATE INDEX automatic_attempts_scope_time ON automatic_attempts(scope_key,attempted_at);
CREATE TABLE worker_status (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    worker_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    heartbeat_at REAL NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running','stopped'))
);
