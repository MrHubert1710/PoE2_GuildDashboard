CREATE TABLE quantity_runs (
    id TEXT PRIMARY KEY,
    league_id TEXT NOT NULL REFERENCES leagues(id),
    input_revision TEXT NOT NULL,
    settings_hash TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    unknown_count INTEGER NOT NULL,
    inferred_count INTEGER NOT NULL,
    excluded_count INTEGER NOT NULL,
    UNIQUE(id,league_id),
    UNIQUE(league_id,input_revision,settings_hash,algorithm_version)
);
CREATE INDEX quantity_runs_league ON quantity_runs(league_id,created_at);
CREATE UNIQUE INDEX transactions_id_league ON transactions(id,league_id);
CREATE TABLE event_quantities (
    league_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES quantity_runs(id),
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    item_name TEXT NOT NULL,
    stash TEXT NOT NULL,
    before_item TEXT,
    quantity_before INTEGER,
    quantity_after INTEGER,
    quantity_delta INTEGER,
    effective_action TEXT NOT NULL CHECK(effective_action IN ('added','removed','unchanged','unknown','mixed','excluded')),
    confidence TEXT NOT NULL CHECK(confidence IN ('source','derived','inferred','unknown','excluded')),
    resolution_reason TEXT NOT NULL,
    PRIMARY KEY(run_id,transaction_id),
    FOREIGN KEY(run_id,league_id) REFERENCES quantity_runs(id,league_id),
    FOREIGN KEY(transaction_id,league_id) REFERENCES transactions(id,league_id)
);
CREATE TABLE quantity_movements (
    run_id TEXT NOT NULL,
    transaction_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    quantity_delta INTEGER NOT NULL CHECK(quantity_delta!=0),
    confidence TEXT NOT NULL,
    PRIMARY KEY(run_id,transaction_id,sequence),
    FOREIGN KEY(run_id,transaction_id) REFERENCES event_quantities(run_id,transaction_id)
);
CREATE TABLE quantity_state (
    league_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES quantity_runs(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    stash TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    quantity INTEGER,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    PRIMARY KEY(run_id,source_id,stash,x,y),
    FOREIGN KEY(run_id,league_id) REFERENCES quantity_runs(id,league_id),
    FOREIGN KEY(transaction_id,league_id) REFERENCES transactions(id,league_id)
);
CREATE TABLE guild_quantity_defaults (
    source_id INTEGER PRIMARY KEY REFERENCES sources(id),
    settings_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX transactions_league_source ON transactions(league_id,source_id);
