-- PDF由来 正規化ストア (docs/datacollection.md SCHEMA 準拠)
CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, title TEXT, publisher TEXT, url TEXT,
  local_path TEXT, doc_sha256 TEXT, n_pages INTEGER,
  fiscal_year INTEGER, license TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS cells (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id TEXT NOT NULL, doc_sha256 TEXT, page_no INTEGER, table_id TEXT,
  row_key TEXT, col_key TEXT,
  value_raw TEXT, value TEXT, value_type TEXT, unit TEXT,
  fiscal_year INTEGER, era_raw TEXT,
  source_text TEXT, source_bbox TEXT, notes_ref TEXT,
  is_total INTEGER DEFAULT 0, merged INTEGER DEFAULT 0,
  unreadable_reason TEXT,
  confidence REAL, extractor TEXT, verified_by TEXT, extracted_at TEXT,
  FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
);
CREATE INDEX IF NOT EXISTS ix_cells_doc ON cells(doc_id, page_no, table_id);
CREATE TABLE IF NOT EXISTS notes (
  note_id TEXT PRIMARY KEY, doc_id TEXT, table_ids TEXT, kind TEXT,
  text TEXT, page INTEGER, blocks_timeseries INTEGER, reason TEXT
);
CREATE TABLE IF NOT EXISTS vocab_areas      (doc_id TEXT, name TEXT, definition TEXT, found_definition INTEGER, pages TEXT);
CREATE TABLE IF NOT EXISTS vocab_indicators (doc_id TEXT, name TEXT, unit TEXT, method TEXT, pages TEXT);
CREATE TABLE IF NOT EXISTS vocab_units      (doc_id TEXT, literal TEXT, quantity TEXT, pages TEXT);
CREATE TABLE IF NOT EXISTS vocab_eras       (doc_id TEXT, literal TEXT, pages TEXT);
CREATE TABLE IF NOT EXISTS extraction_log (
  ts TEXT, doc_id TEXT, page_no INTEGER, table_id TEXT,
  role TEXT, attempt INTEGER, verdict TEXT, failures TEXT, note TEXT
);
