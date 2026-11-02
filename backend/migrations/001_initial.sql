CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    owner_reference TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE leagues (
    id TEXT PRIMARY KEY,
    game TEXT NOT NULL,
    realm TEXT NOT NULL,
    name TEXT NOT NULL,
    lifecycle TEXT NOT NULL DEFAULT 'unknown' CHECK (lifecycle IN ('unknown','active','ended')),
    archived INTEGER NOT NULL DEFAULT 1 CHECK (archived IN (0,1)),
    history_complete INTEGER CHECK (history_complete IN (0,1)),
    fetch_available INTEGER NOT NULL DEFAULT 0 CHECK (fetch_available IN (0,1)),
    settings_json TEXT NOT NULL DEFAULT '{}',
    settings_provenance TEXT NOT NULL DEFAULT 'unknown',
    UNIQUE (game, realm, name)
);
CREATE TABLE league_external_ids (
    league_id TEXT NOT NULL REFERENCES leagues(id),
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    PRIMARY KEY (league_id, provider),
    UNIQUE (provider, external_id, league_id)
);
CREATE TABLE import_runs (
    id TEXT PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running','completed','failed')),
    manifest_sha256 TEXT NOT NULL,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    invalid_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    league_id TEXT NOT NULL REFERENCES leagues(id),
    external_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    account TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('added','removed','modified')),
    stash TEXT NOT NULL,
    item TEXT NOT NULL,
    x INTEGER NOT NULL CHECK (x >= 0),
    y INTEGER NOT NULL CHECK (y >= 0),
    raw_json TEXT NOT NULL,
    normalized_sha256 TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    import_id TEXT NOT NULL REFERENCES import_runs(id),
    UNIQUE (source_id, league_id, external_id)
);
CREATE INDEX transactions_league_date ON transactions(league_id, occurred_at, id);
CREATE INDEX transactions_league_account ON transactions(league_id, account, occurred_at, id);
CREATE INDEX transactions_league_stash ON transactions(league_id, stash, occurred_at, id);
CREATE TABLE archive_files (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    league_id TEXT NOT NULL REFERENCES leagues(id),
    archive_key TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('history','report','chart','price_cache')),
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    provenance_json TEXT NOT NULL,
    import_id TEXT NOT NULL REFERENCES import_runs(id),
    UNIQUE (source_id, league_id, archive_key, sha256)
);
CREATE TABLE revisions (
    id TEXT PRIMARY KEY,
    league_id TEXT NOT NULL REFERENCES leagues(id),
    import_id TEXT NOT NULL REFERENCES import_runs(id),
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('raw_import','report')),
    algorithm_version TEXT NOT NULL,
    price_snapshot_id TEXT
);
CREATE TABLE source_cursors (
    source_id INTEGER NOT NULL REFERENCES sources(id),
    resource TEXT NOT NULL,
    cursor TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source_id, resource)
);
CREATE TABLE catalog_observations (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    etag TEXT
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    resource TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued','running','completed','failed')),
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('automatic','manual')),
    created_at TEXT NOT NULL,
    lease_token TEXT,
    lease_until TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error_code TEXT
);
CREATE TABLE database_checks (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL,
    transaction_count INTEGER NOT NULL,
    last_completed_import_id TEXT REFERENCES import_runs(id),
    result TEXT NOT NULL CHECK (result = 'ok')
);
