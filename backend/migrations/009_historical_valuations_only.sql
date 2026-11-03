-- Drop the retired derived mode; raw transactions and price observations stay intact.
DELETE FROM inventory_value_points WHERE run_id IN (SELECT id FROM valuation_runs WHERE mode='latest');
DELETE FROM valuation_lines WHERE run_id IN (SELECT id FROM valuation_runs WHERE mode='latest');
DELETE FROM valuation_runs WHERE mode='latest';
CREATE TRIGGER valuation_historical_only_insert BEFORE INSERT ON valuation_runs
WHEN NEW.mode!='historical' BEGIN SELECT RAISE(ABORT,'Only historical valuation is supported'); END;
CREATE TRIGGER valuation_historical_only_update BEFORE UPDATE OF mode ON valuation_runs
WHEN NEW.mode!='historical' BEGIN SELECT RAISE(ABORT,'Only historical valuation is supported'); END;
