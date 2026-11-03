ALTER TABLE price_quotes ADD COLUMN effective_at TEXT;
CREATE INDEX price_quotes_time ON price_quotes(name_key,effective_at);
ALTER TABLE price_http_cache ADD COLUMN headers_json TEXT;
