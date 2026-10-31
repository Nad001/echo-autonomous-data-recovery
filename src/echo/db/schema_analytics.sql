PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS fact_transactions (
  record_id TEXT PRIMARY KEY,
  account_id TEXT,
  occurred_at TEXT,
  amount_halalas INTEGER NOT NULL,
  currency TEXT NOT NULL,
  description TEXT,
  source_version INTEGER,
  dest_version INTEGER NOT NULL DEFAULT 1,
  last_sync_run_id TEXT,
  last_transform_version TEXT,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_fact_amount ON fact_transactions(amount_halalas);
CREATE INDEX IF NOT EXISTS idx_fact_dest_ver ON fact_transactions(dest_version);
