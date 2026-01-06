PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS receipts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,

  -- de-dup / provenance
  source_sha    TEXT NOT NULL UNIQUE,
  source_path   TEXT,

  -- extracted fields
  merchant      TEXT,
  receipt_date  TEXT,
  total_amount  REAL,
  currency      TEXT,

  -- stored artifacts
  ocr_text      TEXT,
  ocr_json      TEXT,  -- JSON as text
  du_json       TEXT,  -- JSON as text
  meta_json     TEXT,  -- JSON as text

  created_at    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
  updated_at    TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX IF NOT EXISTS idx_receipts_merchant ON receipts(merchant);
CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(receipt_date);
