-- Technical balancing entries are separate from player operations and raw logs.
CREATE TABLE quantity_reconciliations (
    run_id TEXT NOT NULL,
    transaction_id INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    quantity_delta INTEGER NOT NULL CHECK(quantity_delta!=0),
    confidence TEXT NOT NULL CHECK(confidence='inferred'),
    PRIMARY KEY(run_id,transaction_id,sequence),
    FOREIGN KEY(run_id,transaction_id) REFERENCES event_quantities(run_id,transaction_id)
);
CREATE VIEW quantity_ledger AS
SELECT run_id,transaction_id,sequence,item_name,quantity_delta,confidence,
       NULL AS account,'operation' AS entry_kind FROM quantity_movements
UNION ALL
SELECT run_id,transaction_id,
       CASE WHEN quantity_delta>0 THEN -1000000+sequence ELSE 1000000+sequence END,
       item_name,quantity_delta,confidence,'__poa_reconstruction__','reconstruction'
FROM quantity_reconciliations;
