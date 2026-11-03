ALTER TABLE leagues ADD COLUMN monitored INTEGER NOT NULL DEFAULT 1 CHECK(monitored IN (0,1));
ALTER TABLE leagues ADD COLUMN observed_lifecycle TEXT NOT NULL DEFAULT 'unknown' CHECK(observed_lifecycle IN ('unknown','active','ended'));
UPDATE leagues SET observed_lifecycle=lifecycle;
ALTER TABLE leagues ADD COLUMN observed_source TEXT NOT NULL DEFAULT 'local' CHECK(observed_source IN ('local','ggg','user'));
ALTER TABLE leagues ADD COLUMN observed_at TEXT;
ALTER TABLE leagues ADD COLUMN variant_json TEXT NOT NULL DEFAULT '{}';
CREATE TABLE league_policies (
 league_id TEXT PRIMARY KEY REFERENCES leagues(id),
 lifecycle_override TEXT CHECK(lifecycle_override IN ('unknown','active','ended')),
 version INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL
);
CREATE TABLE league_catalog_entries (
 provider TEXT NOT NULL,
 external_id TEXT NOT NULL,
 game TEXT NOT NULL,
 realm TEXT NOT NULL,
 name TEXT NOT NULL,
 variant_json TEXT NOT NULL,
 lifecycle TEXT NOT NULL CHECK(lifecycle IN ('unknown','active','ended')),
 first_seen TEXT NOT NULL,
 last_seen TEXT NOT NULL,
 present INTEGER NOT NULL CHECK(present IN (0,1)),
 observation_id INTEGER NOT NULL REFERENCES catalog_observations(id),
 payload_json TEXT NOT NULL,
 PRIMARY KEY(provider,game,realm,external_id)
);
CREATE TABLE league_catalog_sources (
 provider TEXT PRIMARY KEY,
 attempted_at TEXT NOT NULL,
 last_success_at TEXT,
 error_code TEXT
);
CREATE TABLE league_catalog_http_cache (
 url TEXT PRIMARY KEY,
 body TEXT,
 etag TEXT,
 expires_at REAL NOT NULL,
 checked_at TEXT NOT NULL,
 error_code TEXT
);
