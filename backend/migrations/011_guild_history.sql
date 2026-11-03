CREATE TABLE guild_history_pages (
 id TEXT PRIMARY KEY,
 source_id INTEGER NOT NULL REFERENCES sources(id),
 import_id TEXT NOT NULL REFERENCES import_runs(id),
 page_number INTEGER NOT NULL,
 requested_from TEXT NOT NULL,
 requested_end TEXT NOT NULL,
 requested_from_id TEXT NOT NULL,
 fetched_at TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 sha256 TEXT NOT NULL
);
CREATE TABLE guild_history_events (
 source_id INTEGER NOT NULL REFERENCES sources(id),
 league_name TEXT NOT NULL,
 external_id TEXT NOT NULL,
 occurred_at TEXT NOT NULL,
 raw_json TEXT NOT NULL,
 normalized_json TEXT NOT NULL,
 transaction_id INTEGER REFERENCES transactions(id),
 page_id TEXT NOT NULL REFERENCES guild_history_pages(id),
 PRIMARY KEY(source_id,league_name,external_id)
);
