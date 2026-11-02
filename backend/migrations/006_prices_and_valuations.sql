CREATE TABLE price_http_cache (
 url TEXT PRIMARY KEY, body TEXT, etag TEXT, expires_at REAL NOT NULL DEFAULT 0,
 checked_at TEXT, error_code TEXT
);
CREATE TABLE price_catalogs (id TEXT PRIMARY KEY,observed_at TEXT NOT NULL,categories_json TEXT NOT NULL);
CREATE TABLE price_categories (
 feed TEXT NOT NULL,category TEXT NOT NULL,label TEXT NOT NULL,active INTEGER NOT NULL,
 catalog_id TEXT NOT NULL REFERENCES price_catalogs(id),PRIMARY KEY(feed,category)
);
CREATE TABLE price_snapshots (
 id TEXT PRIMARY KEY,league_id TEXT NOT NULL REFERENCES leagues(id),feed TEXT NOT NULL,
 category TEXT NOT NULL,observed_at TEXT NOT NULL,effective_at TEXT,provenance TEXT NOT NULL,
 sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,currency TEXT NOT NULL,
 UNIQUE(league_id,feed,category,sha256,provenance)
);
CREATE INDEX price_snapshots_time ON price_snapshots(league_id,effective_at);
CREATE TABLE price_quotes (
 snapshot_id TEXT NOT NULL REFERENCES price_snapshots(id),quote_key TEXT NOT NULL,
 name TEXT NOT NULL,name_key TEXT NOT NULL,price_atomic TEXT NOT NULL,variant TEXT,
 PRIMARY KEY(snapshot_id,quote_key)
);
CREATE INDEX price_quotes_name ON price_quotes(name_key,snapshot_id);
CREATE TABLE price_aliases (
 league_id TEXT NOT NULL REFERENCES leagues(id),source_key TEXT NOT NULL,target_key TEXT NOT NULL,
 PRIMARY KEY(league_id,source_key)
);
CREATE TABLE valuation_runs (
 id TEXT PRIMARY KEY,quantity_run_id TEXT NOT NULL REFERENCES quantity_runs(id),
 league_id TEXT NOT NULL REFERENCES leagues(id),price_revision TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('historical','latest')),algorithm_version TEXT NOT NULL,
 created_at TEXT NOT NULL,UNIQUE(quantity_run_id,price_revision,mode,algorithm_version)
);
CREATE TABLE valuation_lines (
 run_id TEXT NOT NULL REFERENCES valuation_runs(id),transaction_id INTEGER NOT NULL REFERENCES transactions(id),
 sequence INTEGER NOT NULL,snapshot_id TEXT,quote_key TEXT,price_atomic TEXT,value_atomic TEXT,
 reason TEXT NOT NULL,PRIMARY KEY(run_id,transaction_id,sequence),
 FOREIGN KEY(snapshot_id,quote_key) REFERENCES price_quotes(snapshot_id,quote_key)
);
