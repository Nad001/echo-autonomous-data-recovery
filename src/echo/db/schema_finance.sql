PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS accounts (
  account_id TEXT PRIMARY KEY,
  account_type TEXT,
  region TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
  record_id TEXT PRIMARY KEY,
  account_id TEXT,
  occurred_at TEXT,
  amount_halalas INTEGER NOT NULL,
  currency TEXT NOT NULL,
  description TEXT,
  source_version INTEGER NOT NULL,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_txn_occurred ON transactions(occurred_at);
