-- Reconstructed holdings valued at operation times and independent price changes.
CREATE TABLE inventory_value_points (
 run_id TEXT NOT NULL REFERENCES valuation_runs(id),
 sequence INTEGER NOT NULL,
 occurred_at TEXT NOT NULL,
 stash TEXT NOT NULL,
 item_name TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>=0),
 value_atomic TEXT,
 reason TEXT NOT NULL,
 snapshot_id TEXT,
 quote_key TEXT,
 PRIMARY KEY(run_id,sequence,stash,item_name),
 FOREIGN KEY(snapshot_id,quote_key) REFERENCES price_quotes(snapshot_id,quote_key)
);
CREATE INDEX inventory_values_time ON inventory_value_points(run_id,occurred_at,sequence);
