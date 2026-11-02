-- Keep source history and prices; retire generated presentation artifacts.
CREATE TABLE archive_data_files (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    league_id TEXT NOT NULL REFERENCES leagues(id),
    archive_key TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('history','price_cache')),
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    provenance_json TEXT NOT NULL,
    import_id TEXT NOT NULL REFERENCES import_runs(id),
    UNIQUE (source_id, league_id, archive_key, sha256)
);
INSERT INTO archive_data_files SELECT * FROM archive_files WHERE kind IN ('history','price_cache');
DROP TABLE archive_files;
ALTER TABLE archive_data_files RENAME TO archive_files;
