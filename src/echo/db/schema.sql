PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS pipelines (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  current_transform_version TEXT,
  config_override_json TEXT,
  remains_faulty INTEGER NOT NULL DEFAULT 0,
  quarantined_at TEXT,
  resume_blocked_reason TEXT
);

CREATE TABLE IF NOT EXISTS transform_versions (
  id TEXT PRIMARY KEY,
  pipeline_id TEXT NOT NULL,
  name TEXT,
  spec_json TEXT NOT NULL,
  is_trusted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sync_runs (
  id TEXT PRIMARY KEY,
  pipeline_id TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  records_processed INTEGER,
  execution_status TEXT NOT NULL,
  integrity_status TEXT NOT NULL,
  transform_version_id TEXT,
  incident_id TEXT
);

CREATE TABLE IF NOT EXISTS sync_batches (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  batch_seq INTEGER NOT NULL,
  started_at TEXT,
  record_count INTEGER,
  integrity_status TEXT NOT NULL,
  transform_version_id TEXT
);

CREATE TABLE IF NOT EXISTS sync_logs (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  ts TEXT,
  level TEXT,
  message TEXT,
  context_json TEXT
);

CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  run_id TEXT,
  pipeline_id TEXT,
  case_id TEXT,
  severity TEXT,
  detected_at TEXT,
  alert_json TEXT NOT NULL,
  investigation_status TEXT NOT NULL DEFAULT 'pending',
  recovery_status TEXT NOT NULL DEFAULT 'pending',
  review_required INTEGER NOT NULL DEFAULT 0,
  outcome_json TEXT
);

CREATE TABLE IF NOT EXISTS investigation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT,
  payload_json TEXT
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  statement TEXT NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT
);

CREATE TABLE IF NOT EXISTS recovery_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  status TEXT NOT NULL,
  proposal_json TEXT,
  safety_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repair_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_id INTEGER NOT NULL,
  record_id TEXT NOT NULL,
  field TEXT NOT NULL,
  current_value TEXT,
  proposed_value TEXT,
  evidence TEXT,
  source_version INTEGER,
  dest_version INTEGER,
  safety_status TEXT NOT NULL,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS dest_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  record_id TEXT NOT NULL,
  amount_halalas INTEGER,
  description TEXT,
  dest_version INTEGER,
  taken_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL,
  passed INTEGER NOT NULL,
  details_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT,
  pipeline_id TEXT,
  ts TEXT NOT NULL,
  severity TEXT,
  unread INTEGER NOT NULL DEFAULT 1,
  status TEXT,
  summary TEXT,
  link TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT NOT NULL UNIQUE,
  job_type TEXT NOT NULL DEFAULT 'investigate',
  status TEXT NOT NULL,
  lease_until TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id TEXT,
  model TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  latency_ms INTEGER,
  estimated_usd REAL,
  ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  incident_id TEXT,
  run_id TEXT
);

CREATE TABLE IF NOT EXISTS source_trust (
  record_id TEXT PRIMARY KEY,
  trust_state TEXT NOT NULL,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS dest_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id TEXT NOT NULL,
  ts TEXT,
  actor TEXT,
  change_type TEXT,
  payload_json TEXT
);

CREATE TABLE IF NOT EXISTS record_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id TEXT NOT NULL,
  ts TEXT,
  system TEXT NOT NULL,
  field TEXT,
  old_value TEXT,
  new_value TEXT,
  note TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started ON sync_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_batches_run ON sync_batches(run_id, batch_seq);
CREATE INDEX IF NOT EXISTS idx_incidents_run ON incidents(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_events_incident ON investigation_events(incident_id);
CREATE INDEX IF NOT EXISTS idx_notify_unread ON notifications(unread);
